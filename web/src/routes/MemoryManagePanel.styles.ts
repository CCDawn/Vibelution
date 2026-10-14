import { VUI_WORKBENCH_RAIL_CLASS } from "../components/vui";
import {
  vuiControlPillClass,
  vuiControlQuietClass,
} from "../design/vuiChromeRecipes";

const styles = {
  bulkActionBar:
    "bulkActionBar min-w-0 flex flex-wrap items-center gap-1.5 [&_[data-vui=\"button\"]]:w-fit [&_[data-vui=\"button\"]]:max-w-full",
  countPill:
    `countPill min-w-0 ${vuiControlPillClass}`,
  detailActionButton:
    `detailActionButton min-w-0 ${vuiControlQuietClass}`,
  emptyDetail:
    "emptyDetail min-h-[96px] !rounded-none !border-0 !bg-transparent !px-0",
  filterTabs: "filterTabs inline-grid w-fit max-w-full min-w-0 gap-0",
  filterTabsList:
    "filterTabsList inline-flex min-w-0 max-w-full flex-wrap items-center gap-0.5 rounded-[var(--radius-control)] border border-vui-border-subtle bg-[var(--vui-control-muted)] p-0.5",
  filterTabsTrigger:
    "filterTabsTrigger min-w-0 !min-h-8 !px-2 text-vui-xs font-medium data-[state=active]:border-vui-border-subtle data-[state=active]:bg-vui-surface-chat data-[state=active]:text-vui-fg-primary data-[state=active]:shadow-none max-[760px]:!min-h-11",
  // Legacy aliases for style geometry contracts.
  filterButton:
    `filterButton min-w-0 ${vuiControlQuietClass}`,
  filterButtonActive:
    "filterButtonActive min-w-0 border-vui-border-subtle bg-vui-surface-chat text-vui-fg-primary",
  filterGroup:
    "filterGroup min-w-0",
  manageFilterPanel:
    "manageFilterPanel min-w-0 gap-2 border-y border-vui-border-subtle bg-transparent py-2 [&_h2]:text-vui-xs [&_h2]:font-medium",
  manageFormPanel:
    "manageFormPanel grid min-h-0 min-w-0 content-start gap-3 !rounded-none !border-0 !bg-transparent !shadow-none text-vui-xs text-vui-fg-secondary [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full [&>p]:hidden",
  manageListPanel:
    `manageListPanel ${VUI_WORKBENCH_RAIL_CLASS} grid min-h-0 min-w-0 content-start gap-2 overflow-auto px-2 pb-2 pt-3 text-vui-micro-13`,
  manageSourceFilters:
    "manageSourceFilters min-w-0 !grid grid-cols-[repeat(auto-fit,minmax(82px,1fr))] items-center gap-1 max-h-[74px] overflow-auto",
  manageWorkspace:
    "manageWorkspace h-full min-h-0 min-w-0 flex-1 !gap-0 overflow-hidden max-[980px]:!flex-col max-[980px]:!overflow-auto max-[980px]:[&>[data-vui=split-sidebar]]:!w-full max-[980px]:[&>[data-vui=split-sidebar]]:!min-w-0 max-[980px]:[&>[data-vui=split-sidebar]]:!max-w-none max-[980px]:[&>[data-vui=split-sidebar]]:!basis-auto max-[980px]:[&>[data-vui=split-sidebar]]:!min-h-80 max-[980px]:[&>[data-vui=split-main]]:!shrink-0 max-[980px]:[&>[data-vui=split-main]]:!min-h-96 max-[980px]:[&>[role=separator]]:!hidden",
  manageDetailStack: "flex h-full min-h-0 min-w-0 flex-col gap-5 overflow-auto overscroll-contain px-6 py-5 max-[640px]:px-4 [&>.detailPanel]:!h-auto [&>.detailPanel]:!min-h-0 [&>.detailPanel]:!overflow-visible [&>.detailPanel]:!rounded-none [&>.detailPanel]:!border-0 [&>.detailPanel]:!bg-transparent [&>.detailPanel]:!shadow-none",
  managementHeader:
    "managementHeader flex min-w-0 flex-wrap items-center justify-between gap-2 pb-2 [&_h2]:text-vui-xs [&_h2]:font-medium",
  panelEyebrow:
    "panelEyebrow min-w-0 text-vui-2xs font-normal leading-relaxed text-vui-fg-tertiary",
  panelHeader:
    "panelHeader flex min-w-0 flex-wrap items-center justify-between gap-2 px-1 pb-2 [&_h2]:text-vui-xs [&_h2]:font-medium",
  primaryActionButton:
    "primaryActionButton inline-flex min-w-0 w-fit max-w-full !text-vui-xs",
  searchBox:
    "searchBox grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-center gap-2 rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-chat px-2 py-1 text-vui-fg-tertiary [&_input]:!w-full [&_input]:!border-0 [&_input]:!bg-transparent [&_input]:!px-0 [&_input]:!shadow-none",
  sourceChip:
    `sourceChip min-w-0 ${vuiControlPillClass}`,
  sourceChipActive:
    "sourceChipActive min-w-0 border-vui-border-subtle bg-vui-surface-chat text-vui-fg-primary",
  workspace:
    "workspace min-w-0 grid h-full min-h-0 flex-1 gap-2 grid-rows-[minmax(0,1fr)] overflow-auto bg-transparent",
} as const;

export default styles;
