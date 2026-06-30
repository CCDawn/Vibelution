import { GitMerge, LoaderCircle, Save, SearchCheck, ShieldCheck, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { EvolutionActionState, SupervisedWorktreeRun } from "../api/types";
import { VButton } from "../components/vui";
import { useAppI18n } from "../i18n/useAppI18n";
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

const worktreeReviewSurfaceClass = "grid min-h-0 grid-rows-[auto_auto_minmax(0,1fr)] gap-2 overflow-hidden rounded-lg border border-vui-border-soft bg-[var(--surface-panel-strong)] px-3 pb-3 pt-2.5 text-[0.9rem]";
const surfaceHeaderCompactClass = "flex min-w-0 items-center justify-between gap-2.5";
const headerCopyClass = "min-w-0";
const eyebrowClass = "m-0 mb-0.5 text-[0.7rem] uppercase tracking-[0.08em] text-[var(--accent-warm-2)]";
const sectionTitleClass = "m-0 text-base font-bold leading-[1.22] text-vui-fg-primary";
const secondaryPillClass = "inline-flex min-h-6 items-center justify-center rounded-[var(--radius-control)] border border-vui-border-soft bg-[var(--surface-card-muted)] px-2 text-xs font-semibold text-vui-fg-secondary";
const statusPillClass = "inline-flex min-h-6 items-center justify-center rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--accent-warm)_30%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_13%,transparent)] px-2 text-xs font-semibold text-[var(--accent-warm-2)]";
const noticeTextClass = "m-0 break-words text-[var(--vui-font-xs)] leading-[1.45] text-vui-fg-secondary";
const gateNoticeTextClass = "m-0 overflow-hidden break-words text-[var(--vui-font-xs)] leading-[1.35] text-vui-fg-secondary [display:-webkit-box] [-webkit-box-orient:vertical] [-webkit-line-clamp:2]";
const errorTextClass = "m-0 break-words text-[var(--vui-font-xs)] leading-[1.45] text-[var(--state-error)]";
const controlFooterClass = "grid min-h-0 gap-[7px] overflow-auto pr-0.5";
const closedLoopStatusClass = "grid min-h-[30px] min-w-0 grid-cols-[auto_minmax(56px,auto)_minmax(0,1fr)] items-center gap-[7px] rounded-[7px] border border-[var(--border-hairline)] bg-[var(--surface-card-subtle)] px-2 py-1 text-[0.8rem] max-[640px]:grid-cols-1";
const closedLoopStrongClass = "min-w-0 truncate";
const closedLoopMessageClass = "min-w-0 truncate text-[var(--vui-font-xs)] text-vui-fg-secondary";
const worktreeRunPickerClass = "grid min-w-0 gap-[5px]";
const worktreeRunPickerHeaderClass = "flex min-h-5 items-center justify-between gap-2 text-[var(--vui-font-xs)] text-vui-fg-tertiary";
const worktreeRunListClass = "grid max-h-[clamp(92px,16vh,148px)] gap-1 overflow-auto";
const worktreeRunItemClass = "grid min-h-8 min-w-0 grid-cols-[minmax(0,1.25fr)_minmax(78px,0.55fr)_minmax(0,1fr)] items-center gap-2 rounded-[7px] border border-[var(--border-hairline)] bg-[var(--surface-card-muted)] px-2 py-1 text-left text-[0.8rem] text-vui-fg-primary max-[640px]:grid-cols-1";
const worktreeRunItemActiveClass = "border-[color-mix(in_srgb,var(--accent-cool)_34%,var(--border-hairline))] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--surface-card-muted))]";
const worktreeRunItemTopClass = "contents";
const worktreeRunIdClass = "min-w-0 truncate font-[var(--font-mono)] text-[var(--vui-font-xs)] font-semibold text-vui-fg-primary";
const worktreeRunStatusClass = "inline-flex min-h-5 max-w-full items-center justify-self-start truncate rounded-full border border-vui-border-soft bg-[var(--surface-card-subtle)] px-[7px] text-[var(--vui-font-xs)] leading-[1.25] text-vui-fg-secondary";
const worktreeRunMetaClass = "inline-flex min-w-0 items-center justify-self-end truncate text-right text-[var(--vui-font-xs)] leading-[1.25] text-vui-fg-tertiary max-[640px]:justify-self-start max-[640px]:text-left";
const worktreeReviewGateClass = "grid min-w-0 gap-1.5 rounded-[7px] border border-[color-mix(in_srgb,var(--accent-cool)_26%,var(--border-hairline))] bg-[color-mix(in_srgb,var(--accent-cool)_8%,var(--surface-card-subtle))] px-2.5 py-2";
const worktreeActionGateClass = "py-[7px]";
const gateActionGridClass = "grid grid-cols-2 gap-[7px]";
const controlActionsClass = "flex flex-wrap gap-2";
const inlineActionClass = "inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-vui-border-soft bg-[var(--surface-card-muted)] px-3.5 text-[var(--vui-font-xs)] font-semibold text-vui-fg-primary disabled:cursor-not-allowed disabled:opacity-55";
const gateInlineActionClass = "min-h-[34px] min-w-0 px-[9px]";
const dangerInlineActionClass = "border-[color-mix(in_srgb,var(--state-error)_38%,var(--border-soft))] text-[var(--state-error)] hover:bg-[color-mix(in_srgb,var(--state-error)_10%,var(--surface-card-muted))]";
const worktreeReviewHeaderClass = "grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-center gap-2";
const truncateTextClass = "min-w-0 max-w-full truncate";
const metaRowClass = "grid min-w-0 grid-cols-[minmax(90px,auto)_minmax(0,1fr)] gap-2 text-[0.8rem] text-vui-fg-secondary";
const metaValueClass = "min-w-0 truncate";
const spinClass = "animate-spin";

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
    <section className={worktreeReviewSurfaceClass}>
      <div className={surfaceHeaderCompactClass}>
        <div className={headerCopyClass}>
          <p className={eyebrowClass}>{t("closedLoopActive")}</p>
          <h2 className={sectionTitleClass}>{t("worktreeReviewPanelTitle")}</h2>
        </div>
        <span className={secondaryPillClass}>
          {runs.length} {lang === "zh" ? "个候选" : "candidates"}
        </span>
      </div>
      <p className={noticeTextClass}>{t("worktreeReviewPanelHint")}</p>
      <div className={controlFooterClass}>
        {highlightedWorktreeRun ? (
          <div className={closedLoopStatusClass}>
            <span className={secondaryPillClass}>
              {highlightedIsSelfOrigin ? t("selfWorktreeReviewSource") : t("closedLoopActive")}
            </span>
            <strong className={closedLoopStrongClass}>{highlightedWorktreeRun.status || "--"}</strong>
            <span className={closedLoopMessageClass}>{highlightedWorktreeRun.latestMessage || highlightedWorktreeRun.phase || "--"}</span>
          </div>
        ) : null}
        {runs.length > 0 ? (
          <div className={worktreeRunPickerClass}>
            <div className={worktreeRunPickerHeaderClass}>
              <span>{t("worktreeRunHistory")}</span>
              <span>{runs.length}</span>
            </div>
            <div className={worktreeRunListClass}>
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
                    className={selected ? `${worktreeRunItemClass} ${worktreeRunItemActiveClass}` : worktreeRunItemClass}
                    aria-pressed={selected}
                    onClick={() => setSelectedWorktreeRunId(run.runId)}
                  >
                    <span className={worktreeRunItemTopClass}>
                      <strong className={worktreeRunIdClass}>{run.runId || "--"}</strong>
                      <span className={worktreeRunStatusClass}>{statusLabel(run.status)}</span>
                    </span>
                    <span className={worktreeRunMetaClass}>
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
          <div className={`${worktreeReviewGateClass} ${worktreeActionGateClass}`}>
            <div className={gateActionGridClass}>
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
                        ? `${inlineActionClass} ${gateInlineActionClass} ${dangerInlineActionClass}`
                        : `${inlineActionClass} ${gateInlineActionClass}`
                    }
                    isDisabled={disabled}
                    onClick={() => onRunAction(highlightedWorktreeRun, item.action)}
                    title={reason || t(item.labelKey)}
                  >
                    {pending ? <LoaderCircle size={15} className={spinClass} /> : <Icon size={15} />}
                    {t(item.labelKey)}
                  </VButton>
                );
              })}
            </div>
          </div>
        ) : null}
        {highlightedIsSelfOrigin && highlightedWorktreeRun ? (
          <div className={worktreeReviewGateClass}>
            <div className={worktreeReviewHeaderClass}>
              <span className={highlightedReviewPending ? statusPillClass : secondaryPillClass}>
                {highlightedReviewPending ? t("selfWorktreeReviewPending") : t("selfWorktreeReviewApprovedStatus")}
              </span>
              <strong className={truncateTextClass} title={highlightedSelfOrigin?.goal || highlightedWorktreeRun.runId}>
                {highlightedSelfOrigin?.goal || highlightedWorktreeRun.runId}
              </strong>
            </div>
            <p className={gateNoticeTextClass}>
              {highlightedReviewGate?.reason || highlightedSelfOrigin?.riskReason || t("selfWorktreeReviewHint")}
            </p>
            {highlightedMergeBlockers.length > 0 ? (
              <div className={metaRowClass}>
                <span className={metaValueClass}>{t("selfWorktreeMergeBlockers")}</span>
                <span className={metaValueClass}>{highlightedMergeBlockers.join(", ")}</span>
              </div>
            ) : null}
            <div className={controlActionsClass}>
              <VButton
                type="button"
                className={inlineActionClass}
                isDisabled={
                  !highlightedApproveReviewAction?.enabled
                  || pending
                }
                onClick={() => onApproveReview(highlightedWorktreeRun)}
                title={disabledReason(highlightedApproveReviewAction) || t("approveSelfWorktreeReview")}
              >
                {pending ? <LoaderCircle size={15} className={spinClass} /> : <ShieldCheck size={15} />}
                {t("approveSelfWorktreeReview")}
              </VButton>
              {!highlightedApproveReviewAction?.enabled && disabledReason(highlightedApproveReviewAction) ? (
                <p className={gateNoticeTextClass}>{disabledReason(highlightedApproveReviewAction)}</p>
              ) : null}
              {highlightedReviewPending ? (
                <p className={gateNoticeTextClass}>{t("selfWorktreeMergeRequiresReview")}</p>
              ) : null}
            </div>
          </div>
        ) : null}
        {feedback ? <p className={noticeTextClass}>{feedback}</p> : null}
        {error ? <p className={errorTextClass}>{error}</p> : null}
      </div>
    </section>
  );
}
