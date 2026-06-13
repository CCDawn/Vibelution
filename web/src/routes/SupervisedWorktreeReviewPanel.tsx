import { GitMerge, LoaderCircle, Save, SearchCheck, ShieldCheck, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { EvolutionActionState, SupervisedWorktreeRun } from "../api/types";
import { useAppI18n } from "../i18n/useAppI18n";
import styles from "./SupervisedWorktreeReviewPanel.module.css";
import { isSelfEvolutionWorktreeRun } from "./supervisedWorktreeReview";

const WORKTREE_ACTION_ITEMS = [
  {
    action: "analyze_merge",
    stateKey: "analyzeMerge",
    labelKey: "analyzeWorktreeMerge",
    icon: SearchCheck,
  },
  {
    action: "preserve",
    stateKey: "preserve",
    labelKey: "preserveWorktree",
    icon: Save,
  },
  {
    action: "discard",
    stateKey: "discard",
    labelKey: "discardWorktree",
    icon: Trash2,
  },
  {
    action: "merge",
    stateKey: "merge",
    labelKey: "mergeWorktree",
    icon: GitMerge,
  },
] as const;

type SupervisedWorktreeReviewPanelProps = {
  activeRun: SupervisedWorktreeRun | null;
  runs: SupervisedWorktreeRun[];
  pending: boolean;
  feedback: string;
  error: string;
  onApproveReview: (run: SupervisedWorktreeRun) => void;
  onRunAction: (run: SupervisedWorktreeRun, action: string) => void;
};

function worktreeReviewGate(run: SupervisedWorktreeRun | null | undefined) {
  if (!run) {
    return undefined;
  }
  return run.reviewGate ?? run.mergeAnalysis?.reviewGate;
}

function disabledReason(state: EvolutionActionState | undefined) {
  if (!state || state.enabled) {
    return "";
  }
  return state.reason || "";
}

function compactTimestamp(value: string) {
  const text = String(value || "").trim();
  if (!text) {
    return "--";
  }
  const normalized = text.replace("T", " ");
  if (normalized.length > 19) {
    return normalized.slice(0, 19);
  }
  return normalized;
}

export function SupervisedWorktreeReviewPanel({
  activeRun,
  runs,
  pending,
  feedback,
  error,
  onApproveReview,
  onRunAction,
}: SupervisedWorktreeReviewPanelProps) {
  const { lang, t, statusLabel } = useAppI18n();
  const [selectedWorktreeRunId, setSelectedWorktreeRunId] = useState<string | null>(null);
  const selectedWorktreeRun = selectedWorktreeRunId
    ? runs.find((item) => item.runId === selectedWorktreeRunId) ?? null
    : null;
  const highlightedWorktreeRun = activeRun ?? selectedWorktreeRun ?? runs[0] ?? null;
  const highlightedReviewGate = worktreeReviewGate(highlightedWorktreeRun);
  const highlightedSelfOrigin = highlightedWorktreeRun?.selfEvolutionOrigin;
  const highlightedIsSelfOrigin = isSelfEvolutionWorktreeRun(highlightedWorktreeRun);
  const highlightedReviewStatus = String(highlightedReviewGate?.status || "").trim().toLowerCase();
  const highlightedReviewPending = highlightedIsSelfOrigin
    && Boolean(highlightedReviewGate?.required)
    && highlightedReviewStatus !== "approved";
  const highlightedApproveReviewAction = highlightedWorktreeRun?.actionStates?.approveReview;
  const highlightedMergeBlockers = highlightedWorktreeRun?.mergeAnalysis?.blockers ?? [];
  const highlightedWorktreeActions = useMemo(
    () => WORKTREE_ACTION_ITEMS.map((item) => ({
      ...item,
      state: highlightedWorktreeRun?.actionStates?.[item.stateKey],
    })),
    [highlightedWorktreeRun],
  );

  useEffect(() => {
    const activeRunId = activeRun?.runId || "";
    if (activeRunId && activeRunId !== selectedWorktreeRunId) {
      setSelectedWorktreeRunId(activeRunId);
      return;
    }
    if (selectedWorktreeRunId && runs.some((item) => item.runId === selectedWorktreeRunId)) {
      return;
    }
    setSelectedWorktreeRunId(runs[0]?.runId ?? null);
  }, [activeRun?.runId, selectedWorktreeRunId, runs]);

  return (
    <section className={styles.worktreeReviewSurface}>
      <div className={styles.surfaceHeaderCompact}>
        <div>
          <p className={styles.eyebrow}>{t("closedLoopActive")}</p>
          <h2 className={styles.sectionTitle}>{t("worktreeReviewPanelTitle")}</h2>
        </div>
        <span className={styles.secondaryPill}>
          {runs.length} {lang === "zh" ? "个候选" : "candidates"}
        </span>
      </div>
      <p className={styles.noticeText}>{t("worktreeReviewPanelHint")}</p>
      <div className={styles.controlFooter}>
        {highlightedWorktreeRun ? (
          <div className={styles.closedLoopStatus}>
            <span className={styles.secondaryPill}>
              {highlightedIsSelfOrigin ? t("selfWorktreeReviewSource") : t("closedLoopActive")}
            </span>
            <strong>{highlightedWorktreeRun.status || "--"}</strong>
            <span>{highlightedWorktreeRun.latestMessage || highlightedWorktreeRun.phase || "--"}</span>
          </div>
        ) : null}
        {runs.length > 0 ? (
          <div className={styles.worktreeRunPicker}>
            <div className={styles.worktreeRunPickerHeader}>
              <span>{t("worktreeRunHistory")}</span>
              <span>{runs.length}</span>
            </div>
            <div className={styles.worktreeRunList}>
              {runs.slice(0, 4).map((run) => {
                const selected = highlightedWorktreeRun?.runId === run.runId;
                const runReviewGate = worktreeReviewGate(run);
                const runReviewPending = isSelfEvolutionWorktreeRun(run)
                  && Boolean(runReviewGate?.required)
                  && String(runReviewGate?.status || "").trim().toLowerCase() !== "approved";
                return (
                  <button
                    key={run.runId}
                    type="button"
                    className={selected ? `${styles.worktreeRunItem} ${styles.worktreeRunItemActive}` : styles.worktreeRunItem}
                    aria-pressed={selected}
                    onClick={() => setSelectedWorktreeRunId(run.runId)}
                  >
                    <span className={styles.worktreeRunItemTop}>
                      <strong>{run.runId || "--"}</strong>
                      <span>{statusLabel(run.status)}</span>
                    </span>
                    <span className={styles.worktreeRunItemMeta}>
                      {isSelfEvolutionWorktreeRun(run) ? t("selfWorktreeReviewSource") : t("closedLoopActive")}
                      {" · "}
                      {runReviewPending ? t("selfWorktreeReviewPending") : (run.phase || compactTimestamp(run.updatedAt))}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        ) : null}
        {highlightedWorktreeRun ? (
          <div className={`${styles.worktreeReviewGate} ${styles.worktreeActionGate}`}>
            <div className={styles.controlActions}>
              {highlightedWorktreeActions.map((item) => {
                const Icon = item.icon;
                const disabled = !item.state?.enabled || pending;
                const reason = disabledReason(item.state);
                return (
                  <button
                    key={item.action}
                    type="button"
                    className={
                      item.action === "discard" || item.action === "merge"
                        ? `${styles.inlineAction} ${styles.dangerInlineAction}`
                        : styles.inlineAction
                    }
                    disabled={disabled}
                    onClick={() => onRunAction(highlightedWorktreeRun, item.action)}
                    title={reason || t(item.labelKey)}
                  >
                    {pending ? <LoaderCircle size={15} className={styles.spin} /> : <Icon size={15} />}
                    {t(item.labelKey)}
                  </button>
                );
              })}
            </div>
          </div>
        ) : null}
        {highlightedIsSelfOrigin && highlightedWorktreeRun ? (
          <div className={styles.worktreeReviewGate}>
            <div className={styles.worktreeReviewHeader}>
              <span className={highlightedReviewPending ? styles.statusPill : styles.secondaryPill}>
                {highlightedReviewPending ? t("selfWorktreeReviewPending") : t("selfWorktreeReviewApprovedStatus")}
              </span>
              <strong className={styles.truncateText} title={highlightedSelfOrigin?.goal || highlightedWorktreeRun.runId}>
                {highlightedSelfOrigin?.goal || highlightedWorktreeRun.runId}
              </strong>
            </div>
            <p className={styles.noticeText}>
              {highlightedReviewGate?.reason || highlightedSelfOrigin?.riskReason || t("selfWorktreeReviewHint")}
            </p>
            {highlightedMergeBlockers.length > 0 ? (
              <div className={styles.metaRow}>
                <span>{t("selfWorktreeMergeBlockers")}</span>
                <span>{highlightedMergeBlockers.join(", ")}</span>
              </div>
            ) : null}
            <div className={styles.controlActions}>
              <button
                type="button"
                className={styles.inlineAction}
                disabled={
                  !highlightedApproveReviewAction?.enabled
                  || pending
                }
                onClick={() => onApproveReview(highlightedWorktreeRun)}
                title={disabledReason(highlightedApproveReviewAction) || t("approveSelfWorktreeReview")}
              >
                {pending ? <LoaderCircle size={15} className={styles.spin} /> : <ShieldCheck size={15} />}
                {t("approveSelfWorktreeReview")}
              </button>
              {!highlightedApproveReviewAction?.enabled && disabledReason(highlightedApproveReviewAction) ? (
                <p className={styles.noticeText}>{disabledReason(highlightedApproveReviewAction)}</p>
              ) : null}
              {highlightedReviewPending ? (
                <p className={styles.noticeText}>{t("selfWorktreeMergeRequiresReview")}</p>
              ) : null}
            </div>
          </div>
        ) : null}
        {feedback ? <p className={styles.noticeText}>{feedback}</p> : null}
        {error ? <p className={styles.errorText}>{error}</p> : null}
      </div>
    </section>
  );
}
