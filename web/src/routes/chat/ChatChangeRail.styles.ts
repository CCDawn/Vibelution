import { vuiStateSelectedRowClass } from "../../design/vuiSurfaceRecipes";

const styles = {
  rail: "vui-routes-chatchangerail rail flex h-full min-h-0 min-w-0 flex-col !overflow-hidden",
  header: "vui-routes-chatchangerail header flex min-w-0 shrink-0 items-center justify-between gap-2 px-2 pb-1 pt-2",
  headerToggle: "vui-routes-chatchangerail headerToggle flex min-w-0 flex-1 items-center gap-1.5 border-0 bg-transparent p-0 text-left",
  chevron: "vui-routes-chatchangerail chevron inline-block shrink-0 text-[var(--fg-tertiary)] transition-transform",
  chevronCollapsed: "vui-routes-chatchangerail chevronCollapsed -rotate-90",
  title: "vui-routes-chatchangerail title m-0 min-w-0 truncate [font-size:var(--vui-font-sm)] font-[600] leading-tight text-[var(--fg-secondary)]",
  count: "vui-routes-chatchangerail count inline-flex min-h-5 shrink-0 items-center rounded-full border border-[var(--vui-border-subtle)] px-1.5 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)]",
  list: "vui-routes-chatchangerail list m-0 flex max-h-[38%] min-h-0 shrink-0 list-none flex-col gap-1 overflow-auto px-2 pb-2",
  fileButton:
    "vui-routes-chatchangerail fileButton !h-auto min-h-[var(--vui-control-height-sm)] !w-full !min-w-0 !flex-col !items-start !justify-start gap-0 px-2 py-1 text-left [font-size:var(--vui-font-xs)]",
  fileButtonActive: `vui-routes-chatchangerail fileButtonActive min-w-0 ${vuiStateSelectedRowClass}`,
  fileNameRow: "vui-routes-chatchangerail fileNameRow flex w-full min-w-0 items-center justify-between gap-2",
  fileName: "vui-routes-chatchangerail fileName block min-w-0 truncate font-semibold text-[var(--fg-primary)]",
  fileStatus: "vui-routes-chatchangerail fileStatus shrink-0 text-[var(--fg-tertiary)]",
  filePath: "vui-routes-chatchangerail filePath block min-w-0 truncate text-[var(--fg-tertiary)]",
  body: "vui-routes-chatchangerail body min-h-0 flex-1 overflow-hidden",
  railStacked:
    "vui-routes-chatchangerail railStacked flex h-auto min-h-0 shrink-0 flex-col overflow-hidden",
  railStackedPanel:
    "vui-routes-chatchangerail railStackedPanel flex h-auto min-h-0 shrink-0 flex-col overflow-hidden rounded-vui-panel border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-card)]",
  listStacked: "vui-routes-chatchangerail listStacked m-0 flex max-h-40 min-h-0 shrink-0 list-none flex-col gap-1 overflow-auto px-2 pb-2",
  bodyStacked: "vui-routes-chatchangerail bodyStacked max-h-64 min-h-0 overflow-auto pt-1",
} as const;

export default styles;
