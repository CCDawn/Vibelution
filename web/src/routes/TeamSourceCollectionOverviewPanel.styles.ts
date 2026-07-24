import {
  vuiControlPillClass,
} from "../design/vuiChromeRecipes";

import {
  vuiFlatPanelClass,
  vuiStateDangerSoftClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  empty:
    "empty min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  messageError:
    `messageError min-w-0 ${vuiStateDangerSoftClass} [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]`,
  messageResult:
    "messageResult min-w-0 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  workflowIngestionBoundary:
    "workflowIngestionBoundary min-w-0",
  workflowIngestionHeader:
    "workflowIngestionHeader min-w-0 flex flex-wrap items-center gap-1.5",
  workflowSourceCollectionPanel: `workflowSourceCollectionPanel min-w-0 ${vuiFlatPanelClass} p-2`,
  workflowSourceCollectionPlan:
    "workflowSourceCollectionPlan min-w-0",
  workflowSourceCollectionStats:
    "workflowSourceCollectionStats min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  workflowTag:
    `workflowTag min-w-0 ${vuiControlPillClass}`,
} as const;

export default styles;
