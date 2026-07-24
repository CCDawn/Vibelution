import {
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  cleanupConfirmField:
    "cleanupConfirmField min-w-0 grid gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full",
  cleanupExecuteButton:
    "cleanupExecuteButton min-w-0 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55",
  cleanupExecutePanel: `cleanupExecutePanel min-w-0 ${vuiFlatPanelClass} p-2`,
  cleanupExecutionSummary: `cleanupExecutionSummary min-w-0 ${vuiFlatPanelClass} p-2`,
  cleanupFeedback:
    "cleanupFeedback min-w-0",
  cleanupInlineWarning:
    "cleanupInlineWarning min-w-0 border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
  cleanupPathList:
    "cleanupPathList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto font-mono [font-size:var(--vui-font-xs)] [&_span]:truncate",
  cleanupPreviewCounts: `cleanupPreviewCounts min-w-0 ${vuiFlatPanelClass} p-2`,
  cleanupPreviewItem: `cleanupPreviewItem min-w-0 ${vuiOpaqueRowClass} p-2`,
  cleanupPreviewList: `cleanupPreviewList min-w-0 ${vuiFlatPanelClass} p-2 grid min-h-0 content-start gap-1.5 overflow-auto`,
  cleanupPreviewPanel: `cleanupPreviewPanel min-w-0 ${vuiFlatPanelClass} p-2`,
  cleanupStats:
    "cleanupStats min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  cleanupTargetList:
    "cleanupTargetList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  cleanupTargetPanel: `cleanupTargetPanel min-w-0 ${vuiFlatPanelClass} p-2`,
  cleanupTargetRow: `cleanupTargetRow min-w-0 ${vuiOpaqueRowClass} p-2 !grid grid-cols-[18px_minmax(0,1fr)] items-start gap-2`,
  cleanupWarning:
    "cleanupWarning min-w-0 border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
  cleanupWorkspace:
    "cleanupWorkspace min-w-0 grid h-full min-h-0 flex-1 gap-2 p-2 overflow-auto",
  countPill:
    "countPill min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 [font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  emptyState:
    "emptyState min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  inlineActionButton:
    "inlineActionButton min-w-0 flex flex-wrap items-center gap-1.5 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full justify-center rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55",
  panelHeader:
    "panelHeader min-w-0 flex flex-wrap items-center gap-1.5 px-1 py-0.5",
  summaryCard: `summaryCard min-w-0 ${vuiOpaqueRowClass} grid min-h-[54px] grid-cols-[minmax(0,1fr)_auto] items-center gap-2 px-2 py-1.5 [&>span]:[font-size:var(--vui-font-xs)] [&>strong]:[font-size:var(--vui-font-title)]`,
  summaryGrid: `summaryGrid min-w-0 ${vuiFlatPanelClass} p-2 grid gap-2 grid-cols-[repeat(6,minmax(118px,1fr))] gap-1.5 max-[1180px]:grid-cols-3 max-[720px]:grid-cols-2`,
} as const;

export default styles;
