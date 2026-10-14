import {
  vuiControlPillClass,
  vuiControlQuietClass,
} from "../design/vuiChromeRecipes";

const styles = {
  collapsedFormButton:
    `collapsedFormButton min-w-0 ${vuiControlQuietClass} !flex !h-auto !min-h-9 flex-wrap items-center !justify-start !gap-2 !whitespace-normal [&_small]:break-all max-[640px]:!w-full max-[640px]:!min-h-11`,
  countPill:
    `countPill min-w-0 ${vuiControlPillClass}`,
  detailActionButton:
    `detailActionButton min-w-0 ${vuiControlQuietClass}`,
  emptyDetail:
    "emptyDetail grid min-h-[96px] min-w-0 content-center gap-2 p-3 text-vui-xs leading-relaxed text-vui-fg-tertiary",
  formActionRow:
    "formActionRow flex min-w-0 flex-wrap items-center gap-2 border-t border-vui-border-subtle pt-2 text-vui-xs",
  knowledgeFormGrid:
    "knowledgeFormGrid min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))] gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full",
  linkedSourceLifecycle:
    "linkedSourceLifecycle grid min-w-0 gap-2 border-t border-vui-border-subtle py-3",
  linkedSourceRow:
    "linkedSourceRow grid min-w-0 gap-2 border-b border-vui-border-subtle py-3 text-vui-micro-13 text-vui-fg-secondary last:border-b-0",
  lifecycleError:
    "lifecycleError min-w-0 [font-size:var(--vui-font-xs)] text-[var(--state-error)]",
  lifecycleNotice:
    "lifecycleNotice min-w-0 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)]",
  lifecycleReasonField:
    "lifecycleReasonField min-w-0 grid gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_textarea]:w-full",
  managementHeader:
    "managementHeader flex min-w-0 flex-wrap items-center justify-between gap-2 pb-2 [&_h2]:text-vui-xs [&_h2]:font-medium",
  managementPanel:
    "managementPanel grid min-w-0 content-start gap-3 border-0 bg-transparent py-1 text-vui-micro-13 [&_p]:text-vui-fg-secondary",
  panelEyebrow:
    "panelEyebrow min-w-0 text-vui-2xs font-normal leading-relaxed text-vui-fg-tertiary",
  primaryActionButton:
    "primaryActionButton inline-flex min-w-0 w-fit max-w-full !text-vui-xs",
  sourceGovernanceColumn:
    "sourceGovernanceColumn min-w-0 grid [&_.sourceGovernanceControls]:grid-cols-[minmax(240px,0.92fr)_minmax(250px,1.08fr)]",
  sourceGovernanceControls:
    "sourceGovernanceControls min-w-0 flex flex-wrap items-center gap-1.5",
  sourceGovernanceGrid:
    "sourceGovernanceGrid min-w-0 grid gap-4 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))] max-[640px]:!grid-cols-1",
  sourceRecord:
    "sourceRecord grid min-w-0 gap-2 border-b border-vui-border-subtle py-3 text-vui-micro-13 last:border-b-0 [&_p]:break-words [&_p]:text-vui-fg-secondary",
  sourceRecordActions:
    "sourceRecordActions min-w-0 flex flex-wrap items-center gap-1.5",
  sourceRecordHeader:
    "sourceRecordHeader min-w-0 !grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 [&_strong]:break-words [&_strong]:font-medium",
  sourceRecordList:
    "sourceRecordList grid min-h-0 min-w-0 content-start gap-0 overflow-auto",
  sourceRecordMeta:
    "sourceRecordMeta flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1 break-all text-vui-xs text-vui-fg-secondary",
  statusPill:
    `statusPill min-w-0 ${vuiControlPillClass}`,
  statusPillMuted:
    "statusPillMuted min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  wideField:
    "wideField min-w-0 grid gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full",
} as const;

export default styles;
