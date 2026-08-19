/**
 * Search brief layout.
 * Prefer standard Tailwind utilities (flex + flex-1) over arbitrary grid-cols so
 * production CSS cannot drop the column template and stack rows vertically.
 */
const styles = {
  panel:
    "sourceCollectionSearchBriefPanel min-w-0 grid content-start gap-3 rounded-[var(--radius-panel)] border border-[color:var(--border-soft)] bg-[color:var(--source-workbench-panel)] p-3 shadow-[var(--shadow-subtle)]",
  header:
    "flex min-w-0 items-center justify-between gap-2",
  title:
    "m-0 min-w-0 text-[length:var(--vui-font-md)] font-[780] leading-tight text-[var(--fg-primary)]",
  badge:
    "inline-flex h-6 w-fit shrink-0 items-center rounded-full border border-[color:var(--border-soft)] bg-[color:var(--vui-control-muted)] px-2 [font-size:var(--vui-font-2xs)] font-[720] text-[var(--fg-secondary)]",
  field:
    "grid min-w-0 gap-1.5 [&>span]:flex [&>span]:items-center [&>span]:justify-between [&>span]:gap-2 [&>span]:[font-size:var(--vui-font-2xs)] [&>span]:font-[720] [&>span]:text-[var(--fg-secondary)]",
  required:
    "font-[650] text-[var(--state-danger)]",
  topicTextarea:
    "min-h-[6.5rem] w-full resize-y [font-size:var(--vui-font-xs)] leading-relaxed",
  fieldHint:
    "flex min-w-0 items-start justify-between gap-2 [font-size:var(--vui-font-2xs)] leading-snug text-[var(--fg-tertiary)]",
  section:
    "grid min-w-0 gap-2 border-t border-[color:var(--border-soft)] pt-3",
  sectionHeader:
    "flex min-w-0 flex-wrap items-baseline justify-between gap-x-2 gap-y-0.5 [font-size:var(--vui-font-xs)] font-[760] text-[var(--fg-primary)] [&_span]:[font-size:var(--vui-font-2xs)] [&_span]:font-[500] [&_span]:text-[var(--fg-tertiary)]",
  /** One list chrome; rows are flex lines (not per-item cards). */
  queryList:
    "min-w-0 overflow-hidden rounded-md border border-[color:var(--border-soft)] bg-[color:var(--source-workbench-card)]",
  queryRow:
    "flex w-full min-w-0 items-center gap-2 border-b border-[color:var(--border-soft)] px-2 py-1 last:border-b-0 focus-within:bg-[color:color-mix(in_srgb,var(--accent-cool)_7%,transparent)]",
  queryIndex:
    "w-5 shrink-0 select-none text-center [font-size:var(--vui-font-2xs)] font-[700] tabular-nums text-[var(--fg-tertiary)]",
  queryInputWrap:
    "min-w-0 flex-1",
  /** Kill VNativeInput card chrome inside the list; keep the default focus ring. */
  queryInput:
    "!h-8 !min-h-8 !w-full !min-w-0 !rounded-none !border-0 !bg-transparent !px-1 !py-0 ![font-size:var(--vui-font-xs)] !shadow-none hover:!border-0 focus-visible:!border-0",
  removeButton:
    "inline-flex !size-7 !min-w-7 shrink-0 items-center justify-center !p-0 text-[var(--fg-tertiary)] hover:!bg-[color:color-mix(in_srgb,var(--state-danger)_10%,transparent)] hover:!text-[var(--state-danger)]",
  emptyQueries:
    "px-3 py-3.5 text-center [font-size:var(--vui-font-2xs)] leading-snug text-[var(--fg-tertiary)]",
  addQuery:
    "flex min-w-0 items-center gap-2",
  addInput:
    "!h-9 min-w-0 flex-1 [font-size:var(--vui-font-xs)]",
  addButton:
    "inline-flex !size-9 !min-w-9 shrink-0 items-center justify-center !p-0",
  advanced:
    "border-t border-[color:var(--border-soft)] pt-1 [&>summary]:cursor-pointer [&>summary]:py-2 [&>summary]:[font-size:var(--vui-font-2xs)] [&>summary]:font-[720] [&>summary]:text-[var(--fg-secondary)]",
  advancedBody:
    "grid min-w-0 gap-2.5 pt-1",
  settingsGrid:
    "grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2",
  wide:
    "sm:col-span-2",
  actionRow:
    "flex min-w-0 items-center border-t border-[color:var(--border-soft)] pt-3",
  actionHint:
    "min-w-0 [font-size:var(--vui-font-2xs)] leading-snug text-[var(--fg-tertiary)]",
} as const;

export default styles;
