const styles = {
  panel:
    "sourceCollectionSearchBriefPanel min-w-0 grid content-start gap-3 rounded-[var(--radius-panel)] border border-[color:var(--border-soft)] bg-[color:var(--source-workbench-panel)] p-3 shadow-[var(--shadow-subtle)]",
  header:
    "flex min-w-0 items-center justify-between gap-2",
  title:
    "m-0 min-w-0 text-[length:var(--vui-font-md)] font-[780] leading-tight text-[var(--fg-primary)]",
  badge:
    "inline-flex min-h-6 w-fit shrink-0 items-center rounded-full border border-[color:var(--border-soft)] bg-[color:var(--vui-control-muted)] px-2 [font-size:var(--vui-font-xs)] font-[720] text-[var(--fg-secondary)]",
  field:
    "grid min-w-0 gap-1.5 [&>span]:flex [&>span]:items-center [&>span]:justify-between [&>span]:gap-2 [&>span]:[font-size:var(--vui-font-xs)] [&>span]:font-[720] [&>span]:text-[var(--fg-secondary)]",
  required:
    "rounded px-1 font-[650] text-[var(--state-danger)]",
  topicTextarea:
    "min-h-[7.5rem] w-full resize-y leading-[var(--vui-line-readable)] [font-size:var(--vui-font-sm)]",
  fieldHint:
    "flex min-w-0 items-start justify-between gap-2 [font-size:var(--vui-font-xs)] leading-snug text-[var(--fg-tertiary)]",
  section:
    "grid min-w-0 gap-2 border-t border-[color:var(--border-soft)] pt-3",
  sectionHeader:
    "flex min-w-0 items-baseline justify-between gap-2 [&_strong]:text-[length:var(--vui-font-sm)] [&_strong]:font-[760] [&_strong]:text-[var(--fg-primary)] [&_span]:shrink-0 [&_span]:[font-size:var(--vui-font-xs)] [&_span]:text-[var(--fg-tertiary)]",
  /** Compact list shell — one surface, not N heavy cards (Notion/Linear style). */
  queryList:
    "grid min-w-0 overflow-hidden rounded-[var(--radius-control)] border border-[color:var(--border-soft)] bg-[color:var(--source-workbench-card)] divide-y divide-[color:var(--border-soft)]",
  queryRow:
    "grid min-w-0 grid-cols-[1.5rem_minmax(0,1fr)_1.75rem] items-center gap-1 px-1.5 py-0.5 min-h-9 focus-within:bg-[color:color-mix(in_srgb,var(--accent-cool)_6%,transparent)]",
  queryIndex:
    "tabular-nums text-center [font-size:var(--vui-font-xs)] font-[700] text-[var(--fg-tertiary)]",
  queryInput:
    "min-h-8 w-full min-w-0 border-0 !bg-transparent !px-1 !py-1 [font-size:var(--vui-font-sm)] leading-snug shadow-none focus:!ring-0",
  removeButton:
    "grid size-7 shrink-0 place-items-center !p-0 text-[var(--fg-tertiary)] hover:!bg-[color:color-mix(in_srgb,var(--state-danger)_9%,transparent)] hover:!text-[var(--state-danger)]",
  emptyQueries:
    "px-3 py-4 text-center [font-size:var(--vui-font-xs)] leading-snug text-[var(--fg-tertiary)]",
  /** Add row sits under the list, same width rhythm. */
  addQuery:
    "grid min-w-0 grid-cols-[minmax(0,1fr)_2rem] items-center gap-1.5",
  addInput:
    "min-h-9 w-full [font-size:var(--vui-font-sm)]",
  addButton:
    "grid size-8 shrink-0 place-items-center !p-0",
  advanced:
    "border-t border-[color:var(--border-soft)] pt-1 [&>summary]:cursor-pointer [&>summary]:py-2 [&>summary]:[font-size:var(--vui-font-xs)] [&>summary]:font-[720] [&>summary]:text-[var(--fg-secondary)]",
  advancedBody:
    "grid min-w-0 gap-2.5 pt-1",
  settingsGrid:
    "grid min-w-0 grid-cols-2 gap-2 max-[1180px]:grid-cols-1",
  wide:
    "col-span-2 max-[1180px]:col-span-1",
  actionRow:
    "flex min-w-0 items-center border-t border-[color:var(--border-soft)] pt-3",
  actionHint:
    "min-w-0 [font-size:var(--vui-font-xs)] leading-snug text-[var(--fg-tertiary)]",
} as const;

export default styles;
