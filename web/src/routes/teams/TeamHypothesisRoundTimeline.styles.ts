const styles: Record<string, string> = {
  // Lives inside the challenge-cup question detail panel (300–520px inspector),
  // so grids respond to the container, never the viewport.
  section:
    "grid scroll-mt-5 gap-3 rounded-[var(--vui-radius-panel-soft)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-4 [&_h3]:m-0 [&_h4]:m-0 [&_p]:m-0",
  heading:
    "flex items-start justify-between gap-2.5 [&>div]:grid [&>div]:gap-0.5 [&_h3]:[font-size:var(--vui-font-md)] [&_p]:[font-size:var(--vui-font-2xs)] [&_p]:text-[var(--fg-secondary)]",
  timeline: "grid gap-[9px]",
  roundCard:
    "grid gap-2.5 rounded-[var(--vui-radius-panel-soft)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-card)] p-3",
  roundTopline: "flex flex-wrap items-center justify-between gap-2",
  roundTitle: "flex min-w-0 items-center gap-2 [&_strong]:[font-size:var(--vui-font-xs)]",
  roundMeta:
    "flex flex-wrap items-center gap-x-3 gap-y-1 [font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)]",
  lineage:
    "flex flex-wrap items-center gap-1.5 rounded-[var(--vui-radius-control)] bg-[var(--vui-surface-inset)] px-2.5 py-[9px] [font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)] [&_code]:wrap-anywhere [&_code]:text-[var(--fg-secondary)]",
  candidateList: "grid gap-1.5",
  candidateRow:
    "grid gap-1.5 rounded-[var(--vui-radius-control)] bg-[var(--vui-surface-inset)] p-2.5",
  candidateHead:
    "flex items-center justify-between gap-2 [&_strong]:[font-size:var(--vui-font-2xs)] [&_small]:[font-size:var(--vui-font-2xs)] [&_small]:text-[var(--fg-secondary)]",
  scoreGrid:
    "grid grid-cols-2 gap-1 @min-[400px]:grid-cols-4 [&>div]:grid [&>div]:gap-[2px] [&>div]:rounded-[var(--vui-radius-control)] [&>div]:bg-[var(--vui-surface-card)] [&>div]:p-1.5 [&_span]:text-[10px] [&_span]:text-[var(--fg-secondary)] [&_strong]:[font-size:var(--vui-font-2xs)]",
  reviewCard:
    "grid gap-1.5 rounded-[var(--vui-radius-control)] border border-[var(--vui-border-subtle)] p-2.5 [&>span]:[font-size:var(--vui-font-2xs)] [&>span]:font-[650] [&>span]:tracking-[0.02em] [&>span]:text-[var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-2xs)] [&_p]:leading-[1.5]",
  hint: "m-0 [font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)]",
};

export default styles;
