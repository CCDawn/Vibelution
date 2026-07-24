import {
  vuiControlPillClass,
} from "../design/vuiChromeRecipes";

import {
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  contractDomainGrid:
    "contractDomainGrid min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  contractDomainRow: `contractDomainRow min-w-0 ${vuiOpaqueRowClass} p-2 !grid grid-cols-[minmax(116px,1fr)_minmax(96px,0.8fr)_auto] items-center gap-[3px] px-[5px] py-[3px]`,
  contractForbiddenList:
    "contractForbiddenList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto hidden",
  contractPrinciples: "contractPrinciples min-w-0",
  contractStateGrid:
    "contractStateGrid min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))] hidden",
  countPill:
    `countPill min-w-0 ${vuiControlPillClass}`,
  managementHeader:
    "managementHeader min-w-0 flex flex-wrap items-center gap-1.5",
  panelEyebrow:
    "panelEyebrow min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  usageContractPanel: `usageContractPanel min-w-0 ${vuiFlatPanelClass} p-2`,
} as const;

export default styles;
