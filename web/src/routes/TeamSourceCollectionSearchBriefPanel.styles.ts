const styles = {
  panel:
    "sourceCollectionSearchBriefPanel min-w-0 grid content-start gap-3 rounded-[var(--radius-panel)] border border-[color:var(--border-soft)] bg-[color:var(--source-workbench-panel)] p-3 shadow-[var(--shadow-subtle)]",
  header:
    "flex min-w-0 items-start justify-between gap-2 [&>div]:min-w-0 [&>div]:grid [&>div]:gap-0.5",
  eyebrow:
    "[font-size:var(--vui-font-xs)] font-[760] uppercase tracking-[0.06em] text-[var(--fg-tertiary)]",
  title:
    "m-0 text-[length:var(--vui-font-md)] font-[780] leading-tight text-[var(--fg-primary)]",
  badge:
    "inline-flex min-h-6 w-fit shrink-0 items-center rounded-full border border-[color:var(--border-soft)] bg-[color:var(--vui-control-muted)] px-2 [font-size:var(--vui-font-xs)] font-[720] text-[var(--fg-secondary)]",
  field:
    "grid min-w-0 gap-1.5 [&>span]:flex [&>span]:items-center [&>span]:justify-between [&>span]:gap-2 [&>span]:[font-size:var(--vui-font-xs)] [&>span]:font-[720] [&>span]:text-[var(--fg-secondary)]",
  required:
    "font-[650] text-[var(--state-danger)]",
  topicTextarea:
    "min-h-[5.25rem] resize-y leading-[var(--vui-line-readable)]",
  fieldHint:
    "flex min-w-0 items-start justify-between gap-2 [font-size:var(--vui-font-xs)] leading-snug text-[var(--fg-tertiary)]",
  section:
    "grid min-w-0 gap-2 border-t border-[color:var(--border-soft)] pt-3",
  sectionHeader:
    "flex min-w-0 items-end justify-between gap-2 [&>div]:min-w-0 [&>div]:grid [&>div]:gap-0.5 [&_strong]:text-[length:var(--vui-font-sm)] [&_strong]:text-[var(--fg-primary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:text-[var(--fg-tertiary)]",
  queryList:
    "grid min-w-0 gap-1.5",
  queryRow:
    "grid min-w-0 grid-cols-[1.25rem_minmax(0,1fr)_1.75rem] items-start gap-1.5 rounded-[8px] border border-[color:var(--border-soft)] bg-[color:var(--source-workbench-card)] p-1.5 focus-within:border-[color:var(--accent-cool)] focus-within:ring-2 focus-within:ring-[color:color-mix(in_srgb,var(--accent-cool)_12%,transparent)]",
  queryIndex:
    "grid size-5 place-items-center rounded-full bg-[color:var(--vui-control-muted)] [font-size:var(--vui-font-xs)] font-[760] text-[var(--fg-secondary)]",
  queryInput:
    "min-h-7 w-full border-0 !bg-transparent !px-1 !py-0 [font-size:var(--vui-font-xs)] leading-snug shadow-none focus:!ring-0",
  removeButton:
    "grid size-7 place-items-center !p-0 text-[var(--fg-tertiary)] hover:!bg-[color:color-mix(in_srgb,var(--state-danger)_9%,transparent)] hover:!text-[var(--state-danger)]",
  emptyQueries:
    "rounded-[8px] border border-dashed border-[color:var(--border-soft)] px-2.5 py-3 text-center [font-size:var(--vui-font-xs)] text-[var(--fg-tertiary)]",
  addQuery:
    "grid min-w-0 grid-cols-[minmax(0,1fr)_1.875rem] gap-1.5",
  addButton:
    "grid size-[1.875rem] place-items-center !p-0",
  advanced:
    "border-t border-[color:var(--border-soft)] pt-1 [&>summary]:cursor-pointer [&>summary]:py-2 [&>summary]:[font-size:var(--vui-font-xs)] [&>summary]:font-[720] [&>summary]:text-[var(--fg-secondary)]",
  advancedBody:
    "grid min-w-0 gap-2.5 pt-1",
  settingsGrid:
    "grid min-w-0 grid-cols-2 gap-2 max-[1180px]:grid-cols-1",
  wide:
    "col-span-2 max-[1180px]:col-span-1",
  actionRow:
    "flex min-w-0 items-center justify-between gap-2 border-t border-[color:var(--border-soft)] pt-3",
  actionHint:
    "min-w-0 [font-size:var(--vui-font-xs)] leading-snug text-[var(--fg-tertiary)]",
  primaryAction:
    "shrink-0 border-[color:var(--accent-cool)] !bg-[color:var(--accent-cool)] !text-white hover:!bg-[color:color-mix(in_srgb,var(--accent-cool)_88%,black)]",
} as const;

export default styles;
