import { NavLink } from "react-router-dom";

import { type TranslationKey } from "../i18n/dictionary";
import { useAppI18n } from "../i18n/useAppI18n";
import styles from "./SupervisedWorkspaceTabs.module.css";

export type SupervisedWorkspaceView = "live" | "runs" | "library" | "review";
export type SupervisedWorkspaceTabSummary = Partial<Record<SupervisedWorkspaceView, {
  status: string;
  detail: string;
  count?: number | string;
}>>;

type SupervisedWorkspaceTabsProps = {
  activeView: SupervisedWorkspaceView;
  summaries?: SupervisedWorkspaceTabSummary;
};

const VIEWS: Array<{ key: SupervisedWorkspaceView; href: string; end?: boolean }> = [
  { key: "live", href: "/supervised-evolution", end: true },
  { key: "runs", href: "/supervised-evolution/runs", end: true },
  { key: "library", href: "/supervised-evolution/library", end: true },
  { key: "review", href: "/supervised-evolution/review", end: true },
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

export function SupervisedWorkspaceTabs({ activeView, summaries = {} }: SupervisedWorkspaceTabsProps) {
  const { t } = useAppI18n();

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
            className={({ isActive }) =>
              isActive || activeView === view.key
                ? `${styles.flowTab} ${styles.flowTabActive}`
                : styles.flowTab
            }
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
