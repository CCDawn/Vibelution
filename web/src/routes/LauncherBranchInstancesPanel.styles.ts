import { vuiFlatPanelClass } from "../design/vuiSurfaceRecipes";

const panelSurface = `${vuiFlatPanelClass}`;
const rowSurfaceMuted = "rounded-md border border-vui-border-subtle bg-vui-surface-row";
const styles = {
  panel: `mx-2 mt-1.5 block min-h-0 min-w-0 overflow-hidden ${panelSurface} px-2 py-[7px]`,
  panelHeader:
    "flex min-h-0 min-w-0 flex-wrap items-center justify-between gap-2 border-b border-[var(--border-soft)] pb-1.5",
  panelEyebrow: "m-0 [font-size:var(--vui-font-xs)] uppercase tracking-[0.08em] text-vui-fg-tertiary",
  controlWindow: "m-0 flex min-w-0 items-center gap-1.5 [font-size:var(--vui-font-xs)] text-vui-fg-secondary",
  filterBar: "mt-1.5 flex min-w-0 flex-wrap items-center gap-1.5",
  searchInput: "h-7 min-w-[12rem] flex-auto max-w-sm",
  errorReason: "mt-0.5 block max-w-[18rem] truncate [font-size:var(--vui-font-2xs)] text-vui-fg-tertiary",
  tabBar: "mt-1.5 min-w-0",
  tabLabel: "inline-flex min-w-0 items-center gap-1.5",
  tabCount:
    "inline-flex min-w-5 items-center justify-center rounded-full border border-vui-border-subtle bg-vui-surface-muted px-1.5 py-0.5 [font-size:var(--vui-font-2xs)] text-vui-fg-secondary",
  tabHeader: "mt-1.5 flex min-w-0 flex-wrap items-end justify-between gap-2",
  tabHint: "m-0 min-w-0 [font-size:var(--vui-font-xs)] text-vui-fg-tertiary",
  tabHeaderActions: "flex min-w-0 flex-wrap items-center gap-1.5",
  globalEmpty: "mt-1.5",
  toolbar:
    "mt-1.5 flex min-w-0 flex-wrap items-center justify-between gap-2 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)]",
  toolbarActions: "flex min-w-0 flex-wrap items-center gap-1.5",
  pager: "inline-flex min-w-0 items-center gap-1.5",
  rangeLabel: "min-w-0 truncate text-[var(--fg-muted)]",
  notice: "min-w-0 flex-auto truncate text-[var(--fg-secondary)]",
  noticeError: "min-w-0 flex-auto truncate text-[var(--state-error)]",
  statusTable: `mt-1.5 min-w-0 w-full ${rowSurfaceMuted}`,
  selectCell: "w-9 !px-1",
  branchName: "font-medium text-[var(--fg-primary)]",
  actionCell: "!overflow-visible",
  actionButtons: "flex min-w-0 flex-wrap items-center justify-end gap-1",
  maintenanceFold:
    "mt-2 overflow-hidden rounded-md border border-vui-border-subtle bg-vui-surface-row [&>summary]:flex [&>summary]:cursor-pointer [&>summary]:list-none [&>summary]:items-center [&>summary]:justify-between [&>summary]:gap-2 [&>summary]:px-2 [&>summary]:py-1.5 [&>summary]:[font-size:var(--vui-font-xs)] [&>summary]:font-medium [&>summary]:text-vui-fg-secondary",
  maintenanceBody: "border-t border-vui-border-subtle px-1 pb-1.5",
  confirmList: "m-0 flex list-none flex-col gap-2 p-0 text-left",
  confirmItem: "min-w-0 rounded-md border border-[var(--border-soft)] bg-[var(--vui-surface-row)] px-2 py-1.5",
  confirmName: "m-0 text-[var(--fg-primary)]",
  confirmPath: "m-0 truncate text-[var(--fg-tertiary)]",
  confirmRisks: "m-0 mt-1 list-disc pl-4 text-[var(--state-warning)]",
} as const;

export default styles;
