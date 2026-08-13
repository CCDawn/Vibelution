import { vuiControlQuietChromeClass } from "../design/vuiChromeRecipes";
import { vuiStateSelectedRowClass } from "../design/vuiSurfaceRecipes";

/**
 * Utility popover style hooks.
 * Layout (grid/flex/display) for these hooks is owned by workbench-shell.css.
 * Keep Tailwind here to chrome/state tokens only — do not re-declare display or
 * grid-template that fights the shell CSS cascade.
 */
const styles = {
  gitBranchChip: "vui-app-appshell gitBranchChip max-w-[min(14rem,60%)] min-w-0 shrink truncate",
  gitChipRow:
    "vui-app-appshell gitChipRow flex min-w-0 max-w-full flex-wrap items-center gap-1.5 text-[var(--fg-tertiary)]",
  gitCommitItem:
    "vui-app-appshell gitCommitItem grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-center gap-2 [font-size:var(--vui-font-xs)]",
  gitCommitList: "vui-app-appshell gitCommitList grid min-w-0 gap-1",
  gitDetails: "vui-app-appshell gitDetails group min-w-0",
  gitDetailsSummary:
    "vui-app-appshell gitDetailsSummary inline-flex cursor-pointer list-none items-center gap-1 rounded-[var(--radius-control)] px-1.5 py-0.5 [font-size:var(--vui-font-xs)] font-semibold text-[var(--fg-tertiary)] hover:bg-[var(--vui-surface-row-hover)] hover:text-[var(--fg-secondary)] [&::-webkit-details-marker]:hidden",
  gitFileItem:
    "vui-app-appshell gitFileItem grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-center gap-2 [font-size:var(--vui-font-xs)]",
  gitFileList: "vui-app-appshell gitFileList grid min-w-0 gap-1",
  // VSurface owns card chrome; neutralize legacy shell double border/padding on .gitMiniPanel.
  gitMiniPanel:
    "vui-app-appshell gitMiniPanel grid min-w-0 gap-2.5 !border-0 !bg-transparent !p-0 !shadow-none",
  gitMetricStack: "vui-app-appshell gitMetricStack grid min-w-0 gap-1.5",
  gitMetricStrip: "vui-app-appshell gitMetricStrip min-w-0",
  gitOpenLink: `vui-app-appshell gitOpenLink min-w-0 shrink-0 ${vuiControlQuietChromeClass} !h-7 !min-h-7 !px-2 !text-[11px]`,
  gitPanelHeader:
    "vui-app-appshell gitPanelHeader min-w-0 [&_h3]:[font-size:var(--vui-font-sm)] [&_h3]:font-semibold",
  gitQuietState:
    "vui-app-appshell gitQuietState m-0 min-w-0 [font-size:var(--vui-font-xs)] text-[var(--fg-tertiary)]",
  gitSection: "vui-app-appshell gitSection grid min-w-0 gap-1.5",
  gitSectionHeader:
    "vui-app-appshell gitSectionHeader flex min-w-0 items-center justify-between gap-2 [font-size:var(--vui-font-xs)]",
  gitSummaryLine:
    "vui-app-appshell gitSummaryLine m-0 min-w-0 [font-size:var(--vui-font-xs)] leading-snug text-[var(--fg-secondary)]",
  gitValueChip: "vui-app-appshell gitValueChip shrink-0",
  gitWorktreeItem: "vui-app-appshell gitWorktreeItem grid min-w-0 gap-0.5 [font-size:var(--vui-font-xs)]",
  gitWorktreeList: "vui-app-appshell gitWorktreeList grid min-w-0 gap-1",
  // Full-width grid cell chrome; layout (inline-flex, height) owned by shell CSS.
  utilityButton: `vui-app-appshell utilityButton min-w-0 w-full max-w-full ${vuiControlQuietChromeClass} hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] [&_[data-slot=vui-button-content]]:w-full [&_[data-slot=vui-button-content]]:justify-center [&_[data-slot=vui-button-label]]:inline-flex [&_[data-slot=vui-button-label]]:min-w-0 [&_[data-slot=vui-button-label]]:items-center [&_[data-slot=vui-button-label]]:gap-1.5 [&_[data-slot=vui-button-label]]:overflow-hidden`,
  utilityButtonActive: `vui-app-appshell utilityButtonActive min-w-0 ${vuiStateSelectedRowClass}`,
  utilityButtonGrid: "vui-app-appshell utilityButtonGrid min-w-0",
  utilityFileButton: `vui-app-appshell utilityFileButton min-w-0 ${vuiControlQuietChromeClass} hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] grid [&_[data-slot=vui-button-content]]:w-full [&_[data-slot=vui-button-label]]:grid [&_[data-slot=vui-button-label]]:w-full [&_[data-slot=vui-button-label]]:grid-cols-[minmax(0,1fr)_auto] [&_[data-slot=vui-button-label]]:items-center [&_[data-slot=vui-button-label]]:gap-2`,
  utilityFileButtonActive: `vui-app-appshell utilityFileButtonActive min-w-0 ${vuiStateSelectedRowClass} grid [&_[data-slot=vui-button-content]]:w-full [&_[data-slot=vui-button-label]]:grid [&_[data-slot=vui-button-label]]:w-full [&_[data-slot=vui-button-label]]:grid-cols-[minmax(0,1fr)_auto] [&_[data-slot=vui-button-label]]:items-center [&_[data-slot=vui-button-label]]:gap-2`,
  utilityFileChildren: "vui-app-appshell utilityFileChildren min-w-0",
  utilityFileDir: "vui-app-appshell utilityFileDir min-w-0",
  utilityFileHeader:
    "vui-app-appshell utilityFileHeader min-w-0 flex items-center [&_h3]:[font-size:var(--vui-font-sm)] [&_h3]:font-semibold",
  // VSurface owns card chrome; neutralize legacy shell double border/padding.
  utilityFilePanel:
    "vui-app-appshell utilityFilePanel grid min-w-0 gap-2 !border-0 !bg-transparent !p-0 !shadow-none",
  utilityFileSearch: "vui-app-appshell utilityFileSearch min-w-0",
  utilityFileState: "vui-app-appshell utilityFileState min-w-0",
  utilityFileTree: "vui-app-appshell utilityFileTree min-w-0",
  // Panel chrome owned by workbench-shell.css (.utilityPanel).
  utilityPanel: "vui-app-appshell utilityPanel min-w-0",
  utilityPanelHeader: "vui-app-appshell utilityPanelHeader min-w-0 flex flex-wrap items-center gap-1.5 px-0.5 pb-1",
} as const;

export default styles;
