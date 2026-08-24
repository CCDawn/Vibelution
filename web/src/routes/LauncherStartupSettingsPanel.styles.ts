import {
  vuiFlatPanelClass,
  vuiToolbarFillClass,
} from "../design/vuiSurfaceRecipes";

const panelSurface = `${vuiFlatPanelClass}`;
const primaryControl =
  "inline-flex min-h-7 w-fit max-w-full flex-none items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--accent-primary)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-primary)_12%,var(--vui-control-muted))] px-2 [font-size:var(--vui-font-xs)] leading-none text-vui-fg-primary no-underline hover:border-[color-mix(in_srgb,var(--accent-primary)_44%,transparent)] hover:bg-[color-mix(in_srgb,var(--accent-primary)_18%,var(--vui-control-muted))] disabled:cursor-default disabled:opacity-55 [&[data-vui]]:min-w-0";

const styles = {
  windowModeTabs: "inline-grid w-fit max-w-full min-w-0 gap-0 max-[860px]:justify-self-start",
  windowModeTabsList:
    `inline-flex min-w-0 max-w-full flex-wrap items-center gap-0.5 rounded-[var(--radius-control)] border border-vui-border-subtle ${vuiToolbarFillClass} p-0.5`,
  windowModeTabsTrigger:
    "min-h-[25px] rounded-[calc(var(--radius-control)-2px)] border-0 bg-transparent px-[7px] py-[3px] [font-size:var(--vui-font-xs)] leading-none text-vui-fg-secondary " +
    "data-[state=active]:bg-[color-mix(in_srgb,var(--accent-primary)_12%,var(--vui-control-muted))] data-[state=active]:text-vui-fg-primary",
  windowModeTabLabel: "inline-flex min-w-0 items-center gap-[5px]",
  settingError: "col-span-full [font-size:var(--vui-font-xs)] text-[var(--state-error)]",
  settingField: "grid min-w-0 gap-[3px] [&>span]:[font-size:var(--vui-font-xs)] [&>span]:uppercase [&>span]:tracking-[0.06em] [&>span]:text-[var(--fg-tertiary)] [&>small]:min-w-0 [&>small]:truncate [&>small]:[font-size:var(--vui-font-xs)] [&>small]:text-[var(--fg-secondary)] [&_input]:min-h-7 [&_input]:w-full [&_input]:min-w-0 [&_input]:rounded-[var(--radius-control)] [&_input]:border [&_input]:border-[var(--border-soft)] [&_input]:bg-[var(--vui-surface-row)] [&_input]:px-[7px] [&_input]:py-[3px] [&_input]:[font-size:var(--vui-font-xs)] [&_input]:text-[var(--fg-primary)] [&_select]:min-h-7 [&_select]:w-full [&_select]:min-w-0 [&_select]:rounded-[var(--radius-control)] [&_select]:border [&_select]:border-[var(--border-soft)] [&_select]:bg-[var(--vui-surface-row)] [&_select]:px-[7px] [&_select]:py-[3px] [&_select]:[font-size:var(--vui-font-xs)] [&_select]:text-[var(--fg-primary)]",
  settingToggle: "inline-flex min-h-7 min-w-0 items-center gap-1.5 whitespace-nowrap self-end pb-px [&>span]:[font-size:var(--vui-font-xs)] [&>span]:uppercase [&>span]:tracking-[0.06em] [&>span]:text-[var(--fg-tertiary)] [&_input]:m-0 [&_input]:h-3.5 [&_input]:w-3.5",
  settingsTitle: "m-0 shrink-0 whitespace-nowrap [font-size:var(--vui-font-xs)] uppercase tracking-[0.08em] text-vui-fg-tertiary",
  settingsFold: "block min-w-0 w-full",
  settingsSummary:
    "flex min-w-0 cursor-pointer list-none items-center gap-2 [&::-webkit-details-marker]:hidden [&::-webkit-details-marker]:[display:none]",
  settingsSummaryValue: "min-w-0 flex-auto truncate [font-size:var(--vui-font-xs)] text-vui-fg-primary",
  settingsSummaryHint: "shrink-0 [font-size:var(--vui-font-2xs)] text-vui-fg-tertiary",
  settingsBody:
    "mt-1.5 grid min-h-0 min-w-0 max-h-[46vh] content-start gap-2 overflow-y-auto overflow-x-hidden overscroll-contain pr-0.5 [scrollbar-gutter:stable]",
  settingsSaveButton: `${primaryControl} justify-self-end self-end py-[3px]`,
  settingsStrip: `mx-2 mt-1.5 grid min-h-0 min-w-0 w-full max-w-full gap-2 overflow-hidden ${panelSurface} px-2 py-1.5`,
  settingsPrimary:
    "grid min-w-0 max-w-full grid-cols-[repeat(4,minmax(0,1fr))] items-end gap-1.5 max-[1120px]:grid-cols-[repeat(2,minmax(0,1fr))] max-[620px]:grid-cols-[minmax(0,1fr)]",
  settingsWindow:
    "grid min-w-0 max-w-full grid-cols-[max-content_minmax(140px,0.4fr)_max-content] items-end gap-1.5 max-[860px]:grid-cols-[repeat(2,minmax(0,1fr))] max-[620px]:grid-cols-[minmax(0,1fr)]",
  settingsSecondary:
    "grid min-w-0 max-w-full grid-cols-[minmax(140px,0.4fr)_repeat(2,max-content)] items-end gap-1.5 max-[620px]:grid-cols-[minmax(0,1fr)]",
  spin: "animate-spin",
} as const;

export default styles;
