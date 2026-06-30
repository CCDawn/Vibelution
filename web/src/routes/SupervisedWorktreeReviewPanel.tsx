import { GitMerge, LoaderCircle, Save, SearchCheck, ShieldCheck, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { EvolutionActionState, SupervisedWorktreeRun } from "../api/types";
import { VButton } from "../components/vui";
import { useAppI18n } from "../i18n/useAppI18n";
import { isSelfEvolutionWorktreeRun } from "./supervisedWorktreeReview";
import styles from "./SupervisedWorktreeReviewPanel.styles";

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
    <section className={styles.worktreeReviewSurfaceClass}>
      <div className={styles.surfaceHeaderCompactClass}>
        <div className={styles.headerCopyClass}>
          <p className={styles.eyebrowClass}>{t("closedLoopActive")}</p>
          <h2 className={styles.sectionTitleClass}>{t("worktreeReviewPanelTitle")}</h2>
        </div>
        <span className={styles.secondaryPillClass}>
          {runs.length} {lang === "zh" ? "个候选" : "candidates"}
        </span>
      </div>
      <p className={styles.noticeTextClass}>{t("worktreeReviewPanelHint")}</p>
      <div className={styles.controlFooterClass}>
        {highlightedWorktreeRun ? (
          <div className={styles.closedLoopStatusClass}>
            <span className={styles.secondaryPillClass}>
              {highlightedIsSelfOrigin ? t("selfWorktreeReviewSource") : t("closedLoopActive")}
            </span>
            <strong className={styles.closedLoopStrongClass}>{highlightedWorktreeRun.status || "--"}</strong>
            <span className={styles.closedLoopMessageClass}>{highlightedWorktreeRun.latestMessage || highlightedWorktreeRun.phase || "--"}</span>
          </div>
        ) : null}
        {runs.length > 0 ? (
          <div className={styles.worktreeRunPickerClass}>
            <div className={styles.worktreeRunPickerHeaderClass}>
              <span>{t("worktreeRunHistory")}</span>
              <span>{runs.length}</span>
            </div>
            <div className={styles.worktreeRunListClass}>
              {runs.slice(0, 4).map((run) => {
                const selected = highlightedWorktreeRun?.runId === run.runId;
                const runReviewGate = worktreeReviewGate(run);
                const runReviewPending = isSelfEvolutionWorktreeRun(run)
                  && Boolean(runReviewGate?.required)
                  && String(runReviewGate?.status || "").trim().toLowerCase() !== "approved";
                return (
                  <VButton
                    key={run.runId}
                    type="button"
                    className={selected ? `${styles.worktreeRunItemClass} ${styles.worktreeRunItemActiveClass}` : styles.worktreeRunItemClass}
                    aria-pressed={selected}
                    onClick={() => setSelectedWorktreeRunId(run.runId)}
                  >
                    <span className={styles.worktreeRunItemTopClass}>
                      <strong className={styles.worktreeRunIdClass}>{run.runId || "--"}</strong>
                      <span className={styles.worktreeRunStatusClass}>{statusLabel(run.status)}</span>
                    </span>
                    <span className={styles.worktreeRunMetaClass}>
                      {isSelfEvolutionWorktreeRun(run) ? t("selfWorktreeReviewSource") : t("closedLoopActive")}
                      {" · "}
                      {runReviewPending ? t("selfWorktreeReviewPending") : (run.phase || compactTimestamp(run.updatedAt))}
                    </span>
                  </VButton>
                );
              })}
            </div>
          </div>
        ) : null}
        {highlightedWorktreeRun ? (
          <div className={`${styles.worktreeReviewGateClass} ${styles.worktreeActionGateClass}`}>
            <div className={styles.gateActionGridClass}>
              {highlightedWorktreeActions.map((item) => {
                const Icon = item.icon;
                const disabled = !item.state?.enabled || pending;
                const reason = disabledReason(item.state);
                return (
                  <VButton
                    key={item.action}
                    type="button"
                    className={
                      item.action === "discard" || item.action === "merge"
                        ? `${styles.inlineActionClass} ${styles.gateInlineActionClass} ${styles.dangerInlineActionClass}`
                        : `${styles.inlineActionClass} ${styles.gateInlineActionClass}`
                    }
                    isDisabled={disabled}
                    onClick={() => onRunAction(highlightedWorktreeRun, item.action)}
                    title={reason || t(item.labelKey)}
                  >
                    {pending ? <LoaderCircle size={15} className={styles.spinClass} /> : <Icon size={15} />}
                    {t(item.labelKey)}
                  </VButton>
                );
              })}
            </div>
          </div>
        ) : null}
        {highlightedIsSelfOrigin && highlightedWorktreeRun ? (
          <div className={styles.worktreeReviewGateClass}>
            <div className={styles.worktreeReviewHeaderClass}>
              <span className={highlightedReviewPending ? styles.statusPillClass : styles.secondaryPillClass}>
                {highlightedReviewPending ? t("selfWorktreeReviewPending") : t("selfWorktreeReviewApprovedStatus")}
              </span>
              <strong className={styles.truncateTextClass} title={highlightedSelfOrigin?.goal || highlightedWorktreeRun.runId}>
                {highlightedSelfOrigin?.goal || highlightedWorktreeRun.runId}
              </strong>
            </div>
            <p className={styles.gateNoticeTextClass}>
              {highlightedReviewGate?.reason || highlightedSelfOrigin?.riskReason || t("selfWorktreeReviewHint")}
            </p>
            {highlightedMergeBlockers.length > 0 ? (
              <div className={styles.metaRowClass}>
                <span className={styles.metaValueClass}>{t("selfWorktreeMergeBlockers")}</span>
                <span className={styles.metaValueClass}>{highlightedMergeBlockers.join(", ")}</span>
              </div>
            ) : null}
            <div className={styles.controlActionsClass}>
              <VButton
                type="button"
                className={styles.inlineActionClass}
                isDisabled={
                  !highlightedApproveReviewAction?.enabled
                  || pending
                }
                onClick={() => onApproveReview(highlightedWorktreeRun)}
                title={disabledReason(highlightedApproveReviewAction) || t("approveSelfWorktreeReview")}
              >
                {pending ? <LoaderCircle size={15} className={styles.spinClass} /> : <ShieldCheck size={15} />}
                {t("approveSelfWorktreeReview")}
              </VButton>
              {!highlightedApproveReviewAction?.enabled && disabledReason(highlightedApproveReviewAction) ? (
                <p className={styles.gateNoticeTextClass}>{disabledReason(highlightedApproveReviewAction)}</p>
              ) : null}
              {highlightedReviewPending ? (
                <p className={styles.gateNoticeTextClass}>{t("selfWorktreeMergeRequiresReview")}</p>
              ) : null}
            </div>
          </div>
        ) : null}
        {feedback ? <p className={styles.noticeTextClass}>{feedback}</p> : null}
        {error ? <p className={styles.errorTextClass}>{error}</p> : null}
      </div>
    </section>
  );
}
