import { type TranslationKey } from "../i18n/dictionary";
import { useAppI18n } from "../i18n/useAppI18n";
import styles from "./SupervisedWorkspaceTabs.module.css";

export type SupervisedWorkspaceView = "live" | "runs" | "library" | "review";
export type SupervisedWorkspaceWorkflowStep = "baseline_eval" | "improve" | "rerun_score" | "approval";
export type SupervisedWorkspaceTabSummary = Partial<Record<SupervisedWorkspaceWorkflowStep, {
  status: string;
  detail: string;
  count?: number | string;
}>>;

type SupervisedWorkspaceTabsProps = {
  activeView: SupervisedWorkspaceView;
  activeWorkflowStepId?: SupervisedWorkspaceWorkflowStep | string | null;
  onWorkflowStepSelect?: (stepId: SupervisedWorkspaceWorkflowStep) => void;
  summaries?: SupervisedWorkspaceTabSummary;
};

const WORKFLOW_STEPS: Array<{ key: SupervisedWorkspaceWorkflowStep; view: SupervisedWorkspaceView }> = [
  { key: "baseline_eval", view: "live" },
  { key: "improve", view: "runs" },
  { key: "rerun_score", view: "library" },
  { key: "approval", view: "review" },
];

function supervisedFlowLabel(view: SupervisedWorkspaceView, t: (key: TranslationKey) => string) {
  if (view === "live") {
    return t("supervisedFlowLive");
  }
  if (view === "runs") {
    return t("supervisedFlowRuns");
  }
  if (view === "library") {
    return t("supervisedFlowLibrary");
  }
  return t("supervisedFlowReview");
}

function supervisedFlowHint(view: SupervisedWorkspaceView, t: (key: TranslationKey) => string) {
  if (view === "live") {
    return t("supervisedFlowLiveHint");
  }
  if (view === "runs") {
    return t("supervisedFlowRunsHint");
  }
  if (view === "library") {
    return t("supervisedFlowLibraryHint");
  }
  return t("supervisedFlowReviewHint");
}

export function SupervisedWorkspaceTabs({
  activeView,
  activeWorkflowStepId,
  onWorkflowStepSelect,
  summaries = {},
}: SupervisedWorkspaceTabsProps) {
  const { t } = useAppI18n();
  const normalizedActiveWorkflowStepId = String(activeWorkflowStepId || "").trim();

  return (
    <div className={styles.flowTabs} role="tablist" aria-label={t("navSupervisedEvolution")}>
      {WORKFLOW_STEPS.map((step) => {
        const label = supervisedFlowLabel(step.view, t);
        const hint = supervisedFlowHint(step.view, t);
        const summary = summaries[step.key];
        const selected = normalizedActiveWorkflowStepId
          ? step.key === normalizedActiveWorkflowStepId
          : step.view === activeView;
        return (
          <button
            key={step.key}
            type="button"
            role="tab"
            aria-selected={selected}
            className={selected ? `${styles.flowTab} ${styles.flowTabActive}` : styles.flowTab}
            onClick={() => onWorkflowStepSelect?.(step.key)}
          >
            <span className={styles.stepIndex}>{WORKFLOW_STEPS.indexOf(step) + 1}</span>
            <span className={styles.stepBody}>
              <span className={styles.stepLabel}>{label}</span>
              <span className={styles.stepHint}>{hint}</span>
              {summary ? (
                <span className={styles.stepMeta}>
                  <span>{summary.status}</span>
                  {summary.detail ? <span>{summary.detail}</span> : null}
                </span>
              ) : null}
            </span>
            {summary?.count !== undefined ? (
              <span className={styles.stepCount}>{summary.count}</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
