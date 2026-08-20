const styles: Record<string, string> = {
  // Lives inside the challenge-cup question detail panel (300–520px inspector),
  // so grids respond to the container, never the viewport.
  section:
    "grid scroll-mt-5 gap-3 rounded-[var(--vui-radius-panel-soft)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-4 [&_h3]:m-0 [&_h4]:m-0 [&_p]:m-0",
  heading:
    "flex items-start justify-between gap-2.5 [&>div]:grid [&>div]:gap-0.5 [&_h3]:[font-size:var(--vui-font-md)] [&_p]:[font-size:var(--vui-font-2xs)] [&_p]:text-[var(--fg-secondary)]",
  headingActions: "flex shrink-0 flex-wrap items-center justify-end gap-2",
  candidateList: "grid gap-[9px]",
  candidateCard:
    "grid gap-2 rounded-[var(--vui-radius-panel-soft)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-card)] p-3 data-[selected=true]:border-[var(--accent-cool)]",
  candidateTopline: "flex items-start justify-between gap-2.5",
  candidateLabel:
    "flex min-w-0 items-start gap-2 [&>span]:grid [&>span]:min-w-0 [&>span]:gap-[3px] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:leading-[1.4] [&_small]:[font-size:var(--vui-font-2xs)] [&_small]:text-[var(--fg-secondary)]",
  candidateMeta:
    "flex flex-wrap items-center gap-x-3 gap-y-1 [font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)]",
  summary:
    "grid gap-1.5 rounded-[var(--vui-radius-control)] bg-[var(--vui-surface-inset)] p-2.5 [&>span]:[font-size:var(--vui-font-2xs)] [&>span]:font-[650] [&>span]:tracking-[0.02em] [&>span]:text-[var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-2xs)]",
  actions: "flex flex-wrap items-center gap-2",
  generationState:
    "grid justify-items-start gap-2 [&_p]:[font-size:var(--vui-font-2xs)] [&_p]:text-[var(--fg-secondary)]",
  hint: "m-0 [font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)]",
  trailToggle:
    "cursor-pointer rounded-[var(--vui-radius-control)] border border-[var(--vui-border-subtle)] px-2 py-[2px] text-[var(--fg-secondary)] [font-size:var(--vui-font-2xs)] hover:border-[var(--vui-border)]",
  evidenceTrail:
    "grid gap-2 rounded-[var(--vui-radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-inset)] p-2",
  trailList: "m-0 grid list-none gap-2 p-0",
  trailSource: "[font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)]",
  trailExcerpt: "m-0 [font-size:var(--vui-font-xs)] leading-[1.4]",
  trailHint: "m-0 [font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)]",
  errorText: "m-0 [font-size:var(--vui-font-2xs)] text-[var(--state-danger,var(--state-warning))]",
};

export default styles;
