import {
  vuiControlPillClass,
} from "../design/vuiChromeRecipes";

import {
  vuiFlatPanelClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  countPill:
    `countPill min-w-0 ${vuiControlPillClass}`,
  effectiveGrid:
    "effectiveGrid min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(min(100%,10rem),1fr))] [&_.overviewPanel]:max-h-[min(260px,36vh)] [&_.overviewPanel]:overflow-auto [&_.panelLead]:line-clamp-2",
  overviewPanel: `overviewPanel min-w-0 ${vuiFlatPanelClass} p-2 grid grid-rows-[auto_minmax(0,1fr)] overflow-auto`,
  panelEyebrow:
    "panelEyebrow min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  panelHeader:
    "panelHeader min-w-0 flex flex-wrap items-center gap-1.5 px-1 py-0.5",
} as const;

export default styles;
