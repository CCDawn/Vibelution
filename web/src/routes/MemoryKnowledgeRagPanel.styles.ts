import {
  vuiControlPillClass,
} from "../design/vuiChromeRecipes";

import {
  vuiFlatPanelClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  countPill:
    `countPill min-w-0 ${vuiControlPillClass}`,
  emptyDetail: `emptyDetail min-w-0 grid min-h-[96px] content-center gap-1.5 ${vuiFlatPanelClass} p-2 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]`,
  panelEyebrow:
    "panelEyebrow min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  ragContextCard: `ragContextCard min-w-0 ${vuiFlatPanelClass} p-2 border-[color-mix(in_srgb,var(--accent-warm)_24%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_8%,transparent)] text-[var(--accent-warm)]`,
  ragContextList:
    "ragContextList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto border-[color-mix(in_srgb,var(--accent-warm)_24%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_8%,transparent)] text-[var(--accent-warm)]",
  ragContextMeta:
    "ragContextMeta min-w-0 flex flex-wrap items-center gap-1.5 border-[color-mix(in_srgb,var(--accent-warm)_24%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_8%,transparent)] text-[var(--accent-warm)]",
  ragHealthStrip:
    "ragHealthStrip min-w-0 flex flex-wrap items-center gap-1.5 !grid grid-cols-[repeat(auto-fit,minmax(108px,1fr))] gap-1.5",
  ragPolicyStrip:
    "ragPolicyStrip min-w-0 flex flex-wrap items-center gap-1.5",
  ragPreviewHeader:
    "ragPreviewHeader min-w-0 flex flex-wrap items-center gap-1.5 px-1 py-0.5",
  ragPreviewPanel: `ragPreviewPanel min-w-0 ${vuiFlatPanelClass} p-2`,
} as const;

export default styles;
