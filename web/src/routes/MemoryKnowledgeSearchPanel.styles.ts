import {
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  countPill:
    "countPill min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 [font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  emptyDetail: `emptyDetail min-w-0 grid min-h-[96px] content-center gap-1.5 ${vuiFlatPanelClass} p-2 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]`,
  knowledgeFormGrid:
    "knowledgeFormGrid min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))] gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full",
  knowledgeProposalList:
    "knowledgeProposalList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  knowledgeRow: `knowledgeRow min-w-0 ${vuiOpaqueRowClass} p-2`,
  managementHeader:
    "managementHeader min-w-0 flex flex-wrap items-center gap-1.5",
  managementPanel: `managementPanel min-w-0 ${vuiFlatPanelClass} p-2`,
  panelEyebrow:
    "panelEyebrow min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  statusPill:
    "statusPill min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 [font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
} as const;

export default styles;
