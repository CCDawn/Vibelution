const styles = {
  cloneRow:
    "cloneRow min-w-0 grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2",
  description:
    "description min-w-0 [font-size:var(--vui-font-xs)] leading-snug text-[var(--fg-secondary)]",
  feedback:
    "feedback min-w-0 [font-size:var(--vui-font-xs)] leading-snug text-[var(--fg-secondary)]",
  githubProjectsPanel:
    "githubProjectsPanel grid min-h-0 min-w-0 shrink-0 grid-rows-[auto_minmax(0,auto)] gap-1.5 overflow-hidden",
  list:
    "list max-h-40 min-h-0 overflow-y-auto overflow-x-hidden overscroll-contain pr-0.5 [scrollbar-gutter:stable]",
  meta:
    "meta min-w-0 flex flex-wrap items-center gap-1",
  row:
    "row grid min-w-0 gap-0.5 px-2 py-1.5",
  title:
    "title min-w-0 truncate [font-size:var(--vui-font-sm)] font-semibold text-[var(--fg-primary)]",
} as const;

export default styles;
