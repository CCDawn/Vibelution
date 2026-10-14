import {
  vuiFlatPanelClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  detailHeader:
    "detailHeader flex min-w-0 flex-wrap items-center justify-between gap-2 pb-2 [&_h2]:text-vui-xs [&_h2]:font-medium",
  detailPanel:
    "detailPanel grid h-full min-h-0 min-w-0 content-start gap-3 overflow-auto bg-transparent p-3 text-vui-micro-13",
  emptyDetail:
    "emptyDetail grid min-h-[96px] min-w-0 content-center gap-2 p-3 text-vui-xs leading-relaxed text-vui-fg-tertiary [&[role=alert]]:text-[var(--state-error)]",
  emptyState:
    "emptyState min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  knowledgeItems:
    "knowledgeItems min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  bodyReader: "bodyReader min-w-0 grid gap-2",
  historyList: "historyList min-w-0 grid max-h-[min(62vh,42rem)] content-start gap-2 overflow-auto pr-1",
  historyVersion:
    "historyVersion grid min-w-0 gap-2 border-b border-vui-border-subtle py-3 text-vui-xs text-vui-fg-secondary last:border-b-0",
  historyVersionHeader: "historyVersionHeader min-w-0 flex flex-wrap items-center justify-between gap-2",
  knowledgeBody:
    "knowledgeBody min-h-0 max-h-[min(62vh,42rem)] overflow-auto whitespace-pre-wrap break-words rounded-[var(--radius-control)] bg-vui-surface-row p-3 font-mono text-vui-xs leading-relaxed text-vui-fg-secondary",
  lifecycleDialog: "max-h-[calc(100dvh-2rem)]",
  lifecycleDialogContent: "max-h-[calc(100dvh-2rem)] overflow-y-auto",
  lifecycleError: `lifecycleError min-w-0 flex flex-wrap items-center gap-2 ${vuiFlatPanelClass} border border-[var(--state-error)] p-2 [font-size:var(--vui-font-xs)] text-[var(--state-error)]`,
  managementHeader:
    "managementHeader flex min-w-0 flex-wrap items-center justify-between gap-2 pb-2 [&_h2]:text-vui-xs [&_h2]:font-medium",
  managementPanel:
    "managementPanel grid min-w-0 content-start gap-2 border-b border-vui-border-subtle pb-3 text-vui-micro-13 [&_label]:grid [&_label]:gap-1 [&_label]:text-vui-xs",
  metaGrid:
    "metaGrid grid min-w-0 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))] gap-2 py-2 text-vui-xs text-vui-fg-secondary",
  panelEyebrow:
    "panelEyebrow min-w-0 text-vui-2xs font-normal leading-relaxed text-vui-fg-tertiary",
  revisionForm: "revisionForm min-w-0 grid max-h-[min(62vh,42rem)] content-start gap-2 overflow-auto pr-1 [&_label]:grid [&_label]:gap-1 [&_label]:text-[length:var(--vui-font-xs)] [&_textarea]:min-h-24",
  trustNotice: "trustNotice min-w-0 [font-size:var(--vui-font-xs)] leading-relaxed text-[var(--fg-tertiary)]",
} as const;

export default styles;
