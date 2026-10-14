import { VUI_WORKBENCH_PANE_CLASS } from "../components/vui";
import {
  vuiControlPillClass,
  vuiControlQuietClass,
} from "../design/vuiChromeRecipes";

const styles = {
  cleanupConfirmField:
    "cleanupConfirmField min-w-0 grid gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full",
  cleanupExecuteButton:
    `cleanupExecuteButton min-w-0 ${vuiControlQuietClass}`,
  cleanupExecutePanel:
    `cleanupExecutePanel ${VUI_WORKBENCH_PANE_CLASS} grid min-w-0 [&.cleanupExecutePanel]:!overflow-y-auto content-start gap-3 p-3 text-vui-micro-13`,
  cleanupExecutionSummary:
    "cleanupExecutionSummary flex min-w-0 flex-wrap items-center gap-2 border-t border-vui-border-subtle py-2 text-vui-xs data-[outcome=succeeded]:text-[var(--state-success)] data-[outcome=failed]:text-[var(--state-error)]",
  cleanupFeedback:
    "cleanupFeedback min-w-0 text-vui-xs leading-relaxed data-[tone=error]:text-[var(--state-error)] data-[tone=success]:text-[var(--state-success)]",
  cleanupInlineWarning:
    "cleanupInlineWarning min-w-0 border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
  cleanupPathList:
    "cleanupPathList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto font-mono [font-size:var(--vui-font-xs)] [&_span]:truncate",
  cleanupPreviewCounts:
    "cleanupPreviewCounts flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1 py-1 text-vui-xs text-vui-fg-secondary",
  cleanupPreviewItem:
    "cleanupPreviewItem min-w-0 border-b border-vui-border-subtle py-3 text-vui-micro-13 last:border-b-0 [&_header]:flex [&_header]:flex-wrap [&_header]:justify-between [&_header]:gap-2 [&_strong]:font-medium",
  cleanupPreviewList:
    "cleanupPreviewList grid min-h-0 min-w-0 content-start gap-0 overflow-auto",
  cleanupPreviewPanel:
    `cleanupPreviewPanel ${VUI_WORKBENCH_PANE_CLASS} grid min-w-0 [&.cleanupPreviewPanel]:!overflow-y-auto content-start gap-3 p-3 text-vui-micro-13`,
  cleanupStats:
    "cleanupStats min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  cleanupTargetList:
    "cleanupTargetList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  cleanupTargetPanel:
    `cleanupTargetPanel ${VUI_WORKBENCH_PANE_CLASS} grid min-w-0 [&.cleanupTargetPanel]:!overflow-y-auto content-start gap-3 p-3 text-vui-micro-13`,
  cleanupTargetRow:
    "cleanupTargetRow min-w-0 rounded-[var(--radius-control)] !grid grid-cols-[18px_minmax(0,1fr)] items-start gap-2 px-2 py-2 text-vui-micro-13 hover:bg-vui-surface-row data-[selected=true]:bg-vui-surface-row [&_strong]:block [&_strong]:font-medium [&_small]:block [&_small]:text-vui-xs [&_small]:text-vui-fg-secondary",
  cleanupWarning:
    "cleanupWarning min-w-0 border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
  cleanupWorkspace:
    "cleanupWorkspace min-w-0 grid h-full min-h-0 flex-1 gap-2 overflow-auto",
  countPill:
    `countPill min-w-0 ${vuiControlPillClass}`,
  emptyState:
    "emptyState min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  inlineActionButton:
    "inlineActionButton inline-flex min-w-0 w-fit max-w-full !text-vui-xs",
  panelHeader:
    "panelHeader flex min-w-0 flex-wrap items-center justify-between gap-2 pb-2 [&_h2]:text-vui-xs [&_h2]:font-medium [&_p]:text-vui-xs [&_p]:text-vui-fg-secondary",
  summaryCard:
    "summaryCard flex min-w-0 items-center justify-between gap-2 py-2 text-vui-xs [&>strong]:text-vui-micro-13 [&>strong]:font-medium",
  summaryGrid: `summaryGrid min-w-0 shrink-0`,
} as const;

export default styles;
