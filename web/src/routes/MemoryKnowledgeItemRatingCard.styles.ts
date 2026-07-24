import {
  vuiControlPillClass,
  vuiControlQuietClass,
} from "../design/vuiChromeRecipes";

import {
  vuiOpaqueRowClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  detailActionButton:
    `detailActionButton min-w-0 ${vuiControlQuietClass}`,
  knowledgeItemCard: `knowledgeItemCard min-w-0 ${vuiOpaqueRowClass} p-2`,
  metaGrid:
    "metaGrid min-w-0 flex flex-wrap items-center gap-1.5 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  panelHeader:
    "panelHeader min-w-0 flex flex-wrap items-center gap-1.5 px-1 py-0.5",
  ratingControls:
    "ratingControls min-w-0 flex flex-wrap items-center gap-1.5",
  statusPill:
    `statusPill min-w-0 ${vuiControlPillClass}`,
} as const;

export default styles;
