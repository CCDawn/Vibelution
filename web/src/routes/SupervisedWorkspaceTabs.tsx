import { NavLink } from "react-router-dom";

import { type TranslationKey } from "../i18n/dictionary";
import { useAppI18n } from "../i18n/useAppI18n";
import styles from "./SupervisedWorkspaceTabs.module.css";

export type SupervisedWorkspaceView = "live" | "runs" | "library" | "review";
export type SupervisedWorkspaceWorkflowStep = "baseline_eval" | "improve" | "rerun_score" | "approval";
export type SupervisedWorkspaceTabSummary = Partial<Record<SupervisedWorkspaceView, {
  status: string;
  detail: string;
  count?: number | string;
}>>;

type SupervisedWorkspaceTabsProps = {
  activeView: SupervisedWorkspaceView;
  activeWorkflowStepId?: SupervisedWorkspaceWorkflowStep | string | null;
  summaries?: SupervisedWorkspaceTabSummary;
};

const VIEWS: Array<{ key: SupervisedWorkspaceView; workflowStepId: SupervisedWorkspaceWorkflowStep; href: string; end?: boolean }> = [
  { key: "live", workflowStepId: "baseline_eval", href: "/supervised-evolution", end: true },
  { key: "runs", workflowStepId: "improve", href: "/supervised-evolution/runs", end: true },
  { key: "library", workflowStepId: "rerun_score", href: "/supervised-evolution/library", end: true },
  { key: "review", workflowStepId: "approval", href: "/supervised-evolution/review", end: true },
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

export function SupervisedWorkspaceTabs({ activeView, activeWorkflowStepId, summaries = {} }: SupervisedWorkspaceTabsProps) {
  const { t } = useAppI18n();
  const normalizedActiveWorkflowStepId = String(activeWorkflowStepId || "").trim();

  return (
    <div className={styles.flowTabs} role="tablist" aria-label={t("navSupervisedEvolution")}>
      {VIEWS.map((view) => {
        const label = supervisedFlowLabel(view.key, t);
        const hint = supervisedFlowHint(view.key, t);
        const summary = summaries[view.key];
        return (
          <NavLink
            key={view.key}
            to={view.href}
            end={view.end}
            className={({ isActive }) => {
              const selected = normalizedActiveWorkflowStepId
                ? view.workflowStepId === normalizedActiveWorkflowStepId
                : isActive || activeView === view.key;
              return selected ? `${styles.flowTab} ${styles.flowTabActive}` : styles.flowTab;
            }}
          >
            <span className={styles.stepIndex}>{VIEWS.indexOf(view) + 1}</span>
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
          </NavLink>
        );
      })}
    </div>
  );
}
