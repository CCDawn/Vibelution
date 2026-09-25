import {
  vuiRailFillClass,
  vuiToolbarFillClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  sidebar: `vui-routes-configsettingsnavigation sidebar grid h-full min-h-0 w-full min-w-0 [grid-template-rows:auto_auto_auto_minmax(0,1fr)] gap-4 overflow-hidden border-r border-vui-border-subtle ${vuiRailFillClass} p-4 max-[720px]:h-auto max-[720px]:w-full max-[720px]:[grid-template-rows:auto_auto_auto] max-[720px]:overflow-visible`,
  sidebarHeader: "vui-routes-configsettingsnavigation sidebarHeader grid min-w-0 gap-1",
  searchStack: "vui-routes-configsettingsnavigation searchStack grid min-w-0 gap-2",
  searchField: "vui-routes-configsettingsnavigation searchField grid min-w-0 gap-1",
  searchLabel: "vui-routes-configsettingsnavigation searchLabel m-0 [font-size:var(--vui-font-xs)] font-bold text-vui-fg-tertiary",
  searchResults: "vui-routes-configsettingsnavigation searchResults grid min-w-0 content-start gap-1",
  searchHit: "vui-routes-configsettingsnavigation searchHit !grid min-h-10 !w-full !grid-cols-[minmax(0,1fr)] !justify-stretch rounded-md px-3 text-left [font-size:var(--vui-font-sm)] font-semibold [&_small]:block [&_small]:[font-size:var(--vui-font-xs)] [&_small]:font-medium [&_small]:text-vui-fg-tertiary",
  eyebrow:
    "vui-routes-configsettingsnavigation eyebrow m-0 [font-size:var(--vui-font-xs)] font-bold uppercase tracking-[0.08em] text-vui-fg-tertiary",
  title: "vui-routes-configsettingsnavigation title m-0 text-vui-lg font-extrabold text-vui-fg-primary",
  titleRow: "vui-routes-configsettingsnavigation titleRow flex min-w-0 items-center gap-1.5",
  status:
    "vui-routes-configsettingsnavigation status flex min-h-8 items-center justify-between gap-3 px-1 text-vui-xs font-normal text-vui-fg-secondary",
  statusValue: "vui-routes-configsettingsnavigation statusValue text-vui-fg-primary",
  groupNav: "vui-routes-configsettingsnavigation groupNav grid min-h-0 content-start gap-1 overflow-y-auto pr-1 max-[720px]:overflow-visible max-[720px]:grid-cols-2",
  groupButton:
    "vui-routes-configsettingsnavigation groupButton !grid !min-h-9 !w-full !grid-cols-[minmax(0,1fr)] !justify-stretch !border-transparent rounded-vui-control px-3 text-left text-vui-sm font-medium",
  groupButtonActive:
    "vui-routes-configsettingsnavigation groupButtonActive !text-vui-fg-primary !bg-vui-surface-row !border-transparent !shadow-none",
  pageTabs: `vui-routes-configsettingsnavigation pageTabs flex min-w-0 items-center gap-2 overflow-x-auto border-b border-vui-border-subtle ${vuiToolbarFillClass} !bg-transparent px-0 py-0 [scrollbar-width:thin]`,
  pageButton:
    "vui-routes-configsettingsnavigation pageButton shrink-0 text-vui-sm font-medium",
  pageButtonActive:
    "vui-routes-configsettingsnavigation pageButtonActive !bg-vui-surface-row !text-vui-fg-primary !border-transparent !shadow-none",
} as const;

export default styles;
