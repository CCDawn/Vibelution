import {
  vuiControlPillClass,
  vuiControlQuietClass,
} from "../design/vuiChromeRecipes";

import {
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
  vuiStateSelectedRowClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  collapsedFormButton:
    `collapsedFormButton min-w-0 ${vuiControlQuietClass} grid gap-1 [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full hidden !grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-[7px] min-h-[42px] max-h-[92px]`,
  countPill:
    `countPill min-w-0 ${vuiControlPillClass}`,
  detailActionButton:
    `detailActionButton min-w-0 ${vuiControlQuietClass}`,
  emptyDetail: `emptyDetail min-w-0 grid min-h-[96px] content-center gap-1.5 ${vuiFlatPanelClass} p-2 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]`,
  formActionRow: `formActionRow min-w-0 flex flex-wrap items-center gap-1.5 ${vuiOpaqueRowClass} p-2 grid gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full`,
  knowledgeFormGrid:
    "knowledgeFormGrid min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))] gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full",
  managementHeader:
    "managementHeader min-w-0 flex flex-wrap items-center gap-1.5",
  managementPanel: `managementPanel min-w-0 ${vuiFlatPanelClass} p-2`,
  panelEyebrow:
    "panelEyebrow min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  primaryActionButton:
    `primaryActionButton min-w-0 flex flex-wrap items-center gap-1.5 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full justify-center rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55 ${vuiStateSelectedRowClass}`,
  sourceGovernanceColumn:
    "sourceGovernanceColumn min-w-0 grid [&_.sourceGovernanceControls]:grid-cols-[minmax(240px,0.92fr)_minmax(250px,1.08fr)]",
  sourceGovernanceControls:
    "sourceGovernanceControls min-w-0 flex flex-wrap items-center gap-1.5",
  sourceGovernanceGrid:
    "sourceGovernanceGrid min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  sourceRecord:
    "sourceRecord min-w-0",
  sourceRecordActions:
    "sourceRecordActions min-w-0 flex flex-wrap items-center gap-1.5",
  sourceRecordHeader:
    "sourceRecordHeader min-w-0 flex flex-wrap items-center gap-1.5 !grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2",
  sourceRecordList:
    "sourceRecordList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  sourceRecordMeta:
    "sourceRecordMeta min-w-0 flex flex-wrap items-center gap-1.5",
  statusPill:
    `statusPill min-w-0 ${vuiControlPillClass}`,
  statusPillMuted:
    "statusPillMuted min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  wideField:
    "wideField min-w-0 grid gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full",
} as const;

export default styles;
