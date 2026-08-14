import { vuiControlQuietChromeClass } from "../design/vuiChromeRecipes";
import { vuiStateSelectedRowClass } from "../design/vuiSurfaceRecipes";

/**
 * Utility popover style hooks.
 * Layout (grid/flex/display) for these hooks is owned by workbench-shell.css.
 * Keep Tailwind here to chrome/state tokens only — do not re-declare display or
 * grid-template that fights the shell CSS cascade.
 */
const styles = {
  gitSummaryBranch:
    "vui-app-appshell gitSummaryBranch min-w-0 truncate text-[var(--fg-secondary)] [font-size:var(--vui-font-xs)] font-semibold",
  gitSummaryRow: `vui-app-appshell gitSummaryRow min-w-0 w-full max-w-full ${vuiControlQuietChromeClass} !h-8 !min-h-8 !justify-start !gap-2 !px-2 hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] [&_[data-slot=vui-button-content]]:w-full [&_[data-slot=vui-button-content]]:justify-start [&_[data-slot=vui-button-label]]:inline-flex [&_[data-slot=vui-button-label]]:min-w-0 [&_[data-slot=vui-button-label]]:flex-1 [&_[data-slot=vui-button-label]]:items-center [&_[data-slot=vui-button-label]]:gap-2 [&_[data-slot=vui-button-label]]:overflow-hidden`,
  utilityButton: `vui-app-appshell utilityButton min-w-0 w-full max-w-full ${vuiControlQuietChromeClass} hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] [&_[data-slot=vui-button-content]]:w-full [&_[data-slot=vui-button-content]]:justify-center [&_[data-slot=vui-button-label]]:inline-flex [&_[data-slot=vui-button-label]]:min-w-0 [&_[data-slot=vui-button-label]]:items-center [&_[data-slot=vui-button-label]]:gap-1.5 [&_[data-slot=vui-button-label]]:overflow-hidden`,
  utilityButtonActive: `vui-app-appshell utilityButtonActive min-w-0 ${vuiStateSelectedRowClass}`,
  utilityButtonGrid: "vui-app-appshell utilityButtonGrid min-w-0",
  utilityPanel: "vui-app-appshell utilityPanel min-w-0",
  utilityPanelHeader: "vui-app-appshell utilityPanelHeader min-w-0 flex flex-wrap items-center gap-1.5 px-0.5 pb-1",
} as const;

export default styles;
