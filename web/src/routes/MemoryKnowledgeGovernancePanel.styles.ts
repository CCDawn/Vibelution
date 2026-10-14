import {
  vuiControlPillClass,
  vuiControlQuietClass,
} from "../design/vuiChromeRecipes";

const styles = {
  countPill:
    `countPill min-w-0 ${vuiControlPillClass}`,
  detailActionButton:
    `detailActionButton min-w-0 ${vuiControlQuietClass}`,
  emptyDetail:
    "emptyDetail grid min-h-[96px] min-w-0 content-center gap-2 p-3 text-vui-xs leading-relaxed text-vui-fg-tertiary",
  healthStrip:
    "healthStrip min-w-0 flex flex-wrap items-center gap-1.5",
  knowledgeProposalList:
    "knowledgeProposalList grid min-h-0 min-w-0 content-start gap-0 overflow-auto",
  knowledgeRow:
    "knowledgeRow flex min-w-0 flex-wrap items-center gap-2 border-b border-vui-border-subtle py-2 text-vui-micro-13 last:border-b-0 [&_strong]:font-medium [&_span]:break-words",
  managementHeader:
    "managementHeader flex min-w-0 flex-wrap items-center justify-between gap-2 [&_h2]:text-vui-xs [&_h2]:font-medium",
  managementPanel:
    "managementPanel grid min-w-0 content-start gap-3 border-b border-vui-border-subtle py-3 text-vui-micro-13 last:border-b-0",
  panelEyebrow:
    "panelEyebrow min-w-0 text-vui-2xs font-normal leading-relaxed text-vui-fg-tertiary",
  statusPill:
    `statusPill min-w-0 ${vuiControlPillClass}`,
  statusPillMuted:
    "statusPillMuted min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
} as const;

export default styles;
