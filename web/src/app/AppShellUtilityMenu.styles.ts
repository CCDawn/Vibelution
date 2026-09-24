import { vuiControlQuietChromeClass } from "../design/vuiChromeRecipes";
import { vuiStateSelectedRowClass } from "../design/vuiSurfaceRecipes";

/**
 * Utility popover style hooks.
 * Layout (grid/flex/display) for these hooks is owned by workbench-shell.css.
 * Keep Tailwind here to chrome/state tokens only — do not re-declare display or
 * grid-template that fights the shell CSS cascade.
 */
const styles = {
  gitRowLabel: "vui-app-appshell gitRowLabel min-w-0 flex-1 text-left",
  gitStatusChip: "vui-app-appshell gitStatusChip max-w-[11rem] truncate !border-0 !bg-transparent !p-0 !text-[11px]",
  gitSummaryRow: `vui-app-appshell gitSummaryRow [&_[data-slot=vui-button-content]]:w-full [&_[data-slot=vui-button-label]]:inline-flex [&_[data-slot=vui-button-label]]:justify-between`,
  utilityButton: `vui-app-appshell utilityButton min-w-0 w-full max-w-full ${vuiControlQuietChromeClass} hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] [&_[data-slot=vui-button-content]]:w-full [&_[data-slot=vui-button-content]]:justify-start [&_[data-slot=vui-button-label]]:inline-flex [&_[data-slot=vui-button-label]]:w-full [&_[data-slot=vui-button-label]]:min-w-0 [&_[data-slot=vui-button-label]]:items-center [&_[data-slot=vui-button-label]]:gap-1.5 [&_[data-slot=vui-button-label]]:overflow-hidden`,
  utilityButtonActive: `vui-app-appshell utilityButtonActive min-w-0 ${vuiStateSelectedRowClass}`,
  utilityButtonGrid: "vui-app-appshell utilityButtonGrid min-w-0",
  utilityPanel: "vui-app-appshell utilityPanel min-w-0",
} as const;

export default styles;
