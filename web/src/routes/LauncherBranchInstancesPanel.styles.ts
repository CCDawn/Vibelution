import { vuiFlatPanelClass } from "../design/vuiSurfaceRecipes";

const panelSurface = `${vuiFlatPanelClass}`;
const rowSurfaceMuted = "rounded-md border border-vui-border-subtle bg-vui-surface-row";
const styles = {
  panel: `mx-2 mt-1.5 block min-h-0 min-w-0 overflow-hidden ${panelSurface} px-2 py-[7px]`,
  panelHeader:
    "flex min-h-0 min-w-0 items-baseline border-b border-[var(--border-soft)] pb-1.5",
  panelEyebrow: "m-0 [font-size:var(--vui-font-xs)] uppercase tracking-[0.08em] text-vui-fg-tertiary",
  toolbar:
    "mt-1.5 flex min-w-0 flex-wrap items-center justify-between gap-2 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)]",
  toolbarActions: "flex min-w-0 flex-wrap items-center gap-1.5",
  pager: "inline-flex min-w-0 items-center gap-1.5",
  rangeLabel: "min-w-0 truncate text-[var(--fg-muted)]",
  notice: "min-w-0 flex-auto truncate text-[var(--fg-secondary)]",
  noticeError: "min-w-0 flex-auto truncate text-[var(--state-error)]",
  statusTable: `mt-1.5 min-w-0 ${rowSurfaceMuted}`,
  selectCell: "w-9 !px-1",
  branchName: "font-medium text-[var(--fg-primary)]",
  actionCell: "!overflow-visible",
  actionButtons: "flex min-w-0 flex-wrap items-center justify-end gap-1",
  confirmList: "m-0 flex list-none flex-col gap-2 p-0 text-left",
  confirmItem: "min-w-0 rounded-md border border-[var(--border-soft)] bg-[var(--vui-surface-row)] px-2 py-1.5",
  confirmName: "m-0 text-[var(--fg-primary)]",
  confirmPath: "m-0 truncate text-[var(--fg-tertiary)]",
  confirmRisks: "m-0 mt-1 list-disc pl-4 text-[var(--state-warning)]",
} as const;

export default styles;
