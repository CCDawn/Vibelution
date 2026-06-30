import { type TranslationKey } from "../i18n/dictionary";
import { useAppI18n } from "../i18n/useAppI18n";
import { VButton } from "../components/vui";

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

const flowTabsClass = [
  "grid flex-[1_1_620px] grid-cols-[repeat(4,minmax(92px,1fr))] gap-1 rounded-lg border border-vui-border-soft",
  "min-w-[min(500px,100%)] max-w-[720px] bg-[var(--surface-panel-muted)] p-[3px]",
  "max-[1120px]:min-w-[min(460px,100%)] max-[1120px]:max-w-[600px] max-[1120px]:grid-cols-[repeat(4,minmax(88px,1fr))]",
  "max-[760px]:min-w-0 max-[760px]:flex-[1_1_1px] max-[760px]:grid-cols-[repeat(4,minmax(74px,1fr))]",
].join(" ");
const flowTabClass = [
  "grid min-h-[38px] min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-[5px] rounded-[7px] border border-transparent",
  "bg-transparent p-[4px_6px] text-left font-[inherit] text-vui-fg-secondary no-underline transition-[background,border-color,color] duration-150",
  "hover:bg-vui-surface-row-hover hover:text-vui-fg-primary max-[760px]:min-h-[34px] max-[760px]:p-[4px_5px]",
].join(" ");
const flowTabActiveClass = "border-[color-mix(in_srgb,var(--accent-warm)_28%,var(--border-hairline))] bg-[color-mix(in_srgb,var(--accent-warm)_13%,transparent)] text-[var(--accent-warm-2)]";
const stepIndexClass = "inline-flex h-[19px] w-[19px] items-center justify-center whitespace-nowrap rounded-full border border-vui-border-soft text-[0.66rem] text-vui-fg-tertiary max-[760px]:hidden";
const stepIndexActiveClass = "border-[color-mix(in_srgb,var(--accent-warm)_38%,var(--border-soft))] text-[var(--accent-warm-2)]";
const stepBodyClass = "grid min-w-0 gap-px";
const stepLabelClass = "overflow-hidden text-ellipsis whitespace-nowrap text-[0.76rem] font-bold leading-[1.12] text-vui-fg-primary";
const stepHintClass = "hidden overflow-hidden text-ellipsis whitespace-nowrap text-[0.68rem] leading-[1.2] text-vui-fg-tertiary";
const stepMetaClass = "flex min-w-0 gap-1 text-[0.66rem] leading-[1.12] text-vui-fg-tertiary max-[760px]:hidden";
const stepMetaItemClass = "min-w-0 overflow-hidden text-ellipsis whitespace-nowrap";
const stepCountClass = "inline-flex h-[19px] min-w-[21px] items-center justify-center whitespace-nowrap rounded-full border border-vui-border-soft bg-[var(--surface-card-muted)] px-[5px] text-[0.66rem] font-bold text-vui-fg-secondary";

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
    <div className={flowTabsClass} role="tablist" aria-label={t("navSupervisedEvolution")}>
      {WORKFLOW_STEPS.map((step) => {
        const label = supervisedFlowLabel(step.view, t);
        const hint = supervisedFlowHint(step.view, t);
        const summary = summaries[step.key];
        const selected = normalizedActiveWorkflowStepId
          ? step.key === normalizedActiveWorkflowStepId
          : step.view === activeView;
        return (
          <VButton
            key={step.key}
            type="button"
            role="tab"
            aria-selected={selected}
            className={selected ? `${flowTabClass} ${flowTabActiveClass}` : flowTabClass}
            onClick={() => onWorkflowStepSelect?.(step.key)}
          >
            <span className={selected ? `${stepIndexClass} ${stepIndexActiveClass}` : stepIndexClass}>{WORKFLOW_STEPS.indexOf(step) + 1}</span>
            <span className={stepBodyClass}>
              <span className={stepLabelClass}>{label}</span>
              <span className={stepHintClass}>{hint}</span>
              {summary ? (
                <span className={stepMetaClass}>
                  <span className={stepMetaItemClass}>{summary.status}</span>
                  {summary.detail ? <span className={stepMetaItemClass}>{summary.detail}</span> : null}
                </span>
              ) : null}
            </span>
            {summary?.count !== undefined ? (
              <span className={stepCountClass}>{summary.count}</span>
            ) : null}
          </VButton>
        );
      })}
    </div>
  );
}
