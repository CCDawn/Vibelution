import {
  vuiControlPillClass,
  vuiControlQuietClass,
} from "../design/vuiChromeRecipes";

import {
  vuiFlatPanelClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  copyNotice: `copyNotice min-w-0 ${vuiFlatPanelClass} p-2 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]`,
  countPill:
    `countPill min-w-0 ${vuiControlPillClass}`,
  detailActionButton:
    `detailActionButton min-w-0 ${vuiControlQuietClass}`,
  managementActions:
    "managementActions min-w-0 flex flex-wrap items-center gap-1.5",
  managementHeader:
    "managementHeader min-w-0 flex flex-wrap items-center gap-1.5",
  managementPanel: "managementPanel grid min-w-0 gap-3 border-t border-vui-border-subtle py-4",
  panelEyebrow:
    "panelEyebrow min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  selectedConfigSummary: "selectedConfigSummary grid min-w-0 gap-2 border-t border-vui-border-subtle py-3 text-vui-micro-13 text-vui-fg-secondary",
} as const;

export default styles;
