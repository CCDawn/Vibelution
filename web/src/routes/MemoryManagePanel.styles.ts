const styles = {
  bulkActionBar:
    "bulkActionBar min-w-0 flex flex-wrap items-center gap-1.5 [&_[data-vui=\"button\"]]:w-fit [&_[data-vui=\"button\"]]:max-w-full",
  countPill:
    "countPill min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 [font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  detailActionButton:
    "detailActionButton min-w-0 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55",
  emptyDetail:
    "emptyDetail min-h-[96px]",
  filterButton:
    "filterButton min-w-0 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55",
  filterButtonActive:
    "filterButtonActive min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_11%,transparent)] text-[var(--accent-cool)] border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))]",
  filterGroup:
    "filterGroup min-w-0",
  manageFilterPanel:
    "manageFilterPanel gap-1.5 border-y border-[var(--vui-border-hairline)] py-1.5",
  manageFormPanel:
    "manageFormPanel min-h-0 overflow-auto grid gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full [&>p]:hidden",
  manageListPanel:
    "manageListPanel grid min-h-0 content-start gap-1.5 overflow-auto",
  manageSourceFilters:
    "manageSourceFilters min-w-0 !grid grid-cols-[repeat(auto-fit,minmax(82px,1fr))] items-center gap-1 max-h-[74px] overflow-auto",
  manageWorkspace:
    "manageWorkspace min-w-0 grid h-full min-h-0 gap-2 p-2 grid-cols-[minmax(300px,0.76fr)_minmax(0,1fr)] !grid-rows-[minmax(0,0.58fr)_minmax(0,1fr)] overflow-hidden [&_.manageListPanel]:row-span-2 [&_.detailPanel]:col-start-2 [&_.detailPanel]:row-start-2 [&_.detailPanel]:max-h-none max-[980px]:grid-cols-1 max-[980px]:!grid-rows-none max-[980px]:overflow-auto max-[980px]:[&_.manageListPanel]:row-span-1 max-[980px]:[&_.detailPanel]:col-start-auto max-[980px]:[&_.detailPanel]:row-start-auto",
  managementHeader:
    "managementHeader min-w-0 flex flex-wrap items-center gap-1.5",
  panelEyebrow:
    "panelEyebrow min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  panelHeader:
    "panelHeader min-w-0 flex flex-wrap items-center gap-1.5 px-1 py-0.5",
  primaryActionButton:
    "primaryActionButton min-w-0 flex flex-wrap items-center gap-1.5 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full justify-center rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55 border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))] text-[var(--accent-cool)]",
  searchBox:
    "searchBox min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-1.5",
  sourceChip:
    "sourceChip min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 [font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  sourceChipActive:
    "sourceChipActive min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_11%,transparent)] text-[var(--accent-cool)] border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))]",
  workspace:
    "workspace min-w-0 grid h-full min-h-0 flex-1 gap-2 p-2 grid-rows-[minmax(0,1fr)] overflow-auto",
} as const;

export default styles;
