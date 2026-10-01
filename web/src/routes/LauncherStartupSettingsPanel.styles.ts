import { vuiFlatPanelClass } from "../design/vuiSurfaceRecipes";

const panelSurface = `${vuiFlatPanelClass}`;

const styles = {
  standalonePage: "!h-auto flex-1",
  standaloneHeader: "hidden",
  settingsStrip: `mx-2 mt-1.5 grid min-h-0 min-w-0 w-full max-w-full gap-2 overflow-hidden ${panelSurface} px-2 py-1.5`,
  settingsFold: "block min-w-0 w-full",
  settingsSummary:
    "flex min-w-0 cursor-pointer list-none items-center gap-2 [&::-webkit-details-marker]:hidden [&::-webkit-details-marker]:[display:none]",
  settingsTitle: "m-0 shrink-0 whitespace-nowrap [font-size:var(--vui-font-xs)] uppercase tracking-[0.08em] text-vui-fg-tertiary",
  settingsSummaryValue: "min-w-0 flex-auto truncate [font-size:var(--vui-font-xs)] text-vui-fg-primary",
  settingsSummaryHint: "shrink-0 [font-size:var(--vui-font-2xs)] text-vui-fg-tertiary",
  settingsBody:
    "mt-3 grid min-h-0 min-w-0 max-h-[46vh] content-start gap-3 overflow-y-auto overflow-x-hidden overscroll-contain pr-0.5 [scrollbar-gutter:stable]",
  settingsCompactFooter:
    "flex min-w-0 flex-wrap items-center justify-end gap-1.5 border-t border-vui-border-subtle pt-3 [&>[role=status]]:mr-auto",
  settingsPageBody: "gap-4 pb-6",
  settingsPageContent: "grid w-full max-w-3xl content-start gap-4",
  settingsGroup: "w-full",
  settingsSelect: "w-full",
  settingsConflict:
    "flex min-w-0 flex-wrap items-center justify-between gap-3 rounded-vui-panel border border-[color-mix(in_srgb,var(--state-warning)_35%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-warning)_7%,var(--vui-surface-card))] px-4 py-3 text-vui-sm text-vui-fg-primary",
  settingsFooterStatus: "mr-auto min-w-0 text-vui-xs text-vui-fg-secondary",
  settingsSaveError: "mr-auto min-w-0 text-vui-xs text-[var(--state-error)]",
  spin: "animate-spin motion-reduce:animate-none",
} as const;

export default styles;
