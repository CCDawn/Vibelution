import {
  vuiFlatPanelClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  detailHeader:
    "detailHeader min-w-0 flex flex-wrap items-center gap-1.5 px-1 py-0.5",
  detailPanel: `detailPanel min-w-0 h-full min-h-0 overflow-auto ${vuiFlatPanelClass} p-2`,
  emptyDetail: `emptyDetail min-w-0 grid min-h-[96px] content-center gap-1.5 ${vuiFlatPanelClass} p-2 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]`,
  emptyState:
    "emptyState min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  knowledgeItems:
    "knowledgeItems min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  bodyReader: "bodyReader min-w-0 grid gap-2",
  historyList: "historyList min-w-0 grid max-h-[min(62vh,42rem)] content-start gap-2 overflow-auto pr-1",
  historyVersion: `historyVersion min-w-0 grid gap-1 ${vuiFlatPanelClass} p-2 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)]`,
  historyVersionHeader: "historyVersionHeader min-w-0 flex flex-wrap items-center justify-between gap-2",
  knowledgeBody: `knowledgeBody min-h-0 max-h-[min(62vh,42rem)] overflow-auto whitespace-pre-wrap break-words ${vuiFlatPanelClass} p-3 font-mono [font-size:var(--vui-font-xs)] leading-relaxed text-[var(--fg-secondary)]`,
  lifecycleDialog: "max-h-[calc(100dvh-2rem)]",
  lifecycleDialogContent: "max-h-[calc(100dvh-2rem)] overflow-y-auto",
  lifecycleError: `lifecycleError min-w-0 flex flex-wrap items-center gap-2 ${vuiFlatPanelClass} border border-[var(--state-error)] p-2 [font-size:var(--vui-font-xs)] text-[var(--state-error)]`,
  managementHeader:
    "managementHeader min-w-0 flex flex-wrap items-center gap-1.5",
  managementPanel: `managementPanel min-w-0 ${vuiFlatPanelClass} p-2`,
  metaGrid:
    "metaGrid min-w-0 flex flex-wrap items-center gap-1.5 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  panelEyebrow:
    "panelEyebrow min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  revisionForm: "revisionForm min-w-0 grid max-h-[min(62vh,42rem)] content-start gap-2 overflow-auto pr-1 [&_label]:grid [&_label]:gap-1 [&_label]:text-[length:var(--vui-font-xs)] [&_textarea]:min-h-24",
  trustNotice: "trustNotice min-w-0 [font-size:var(--vui-font-xs)] leading-relaxed text-[var(--fg-tertiary)]",
} as const;

export default styles;
