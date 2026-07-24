import {
  vuiControlPillClass,
  vuiControlQuietClass,
} from "../design/vuiChromeRecipes";

import {
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  countPill:
    `countPill min-w-0 ${vuiControlPillClass}`,
  detailActionButton:
    `detailActionButton min-w-0 ${vuiControlQuietClass}`,
  emptyDetail: `emptyDetail min-w-0 grid min-h-[96px] content-center gap-1.5 ${vuiFlatPanelClass} p-2 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]`,
  healthStrip:
    "healthStrip min-w-0 flex flex-wrap items-center gap-1.5",
  knowledgeProposalList:
    "knowledgeProposalList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  knowledgeRow: `knowledgeRow min-w-0 ${vuiOpaqueRowClass} p-2`,
  managementHeader:
    "managementHeader min-w-0 flex flex-wrap items-center gap-1.5",
  managementPanel: `managementPanel min-w-0 ${vuiFlatPanelClass} p-2`,
  panelEyebrow:
    "panelEyebrow min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  statusPill:
    `statusPill min-w-0 ${vuiControlPillClass}`,
  statusPillMuted:
    "statusPillMuted min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
} as const;

export default styles;
