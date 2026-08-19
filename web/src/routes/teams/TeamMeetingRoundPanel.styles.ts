const styles: Record<string, string> = {
  // Lives inside the challenge-cup question detail panel (300–520px inspector),
  // so grids respond to the container, never the viewport.
  section:
    "grid scroll-mt-5 gap-3 rounded-[var(--vui-radius-panel-soft)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-4 [&_h3]:m-0 [&_h4]:m-0 [&_p]:m-0",
  heading:
    "flex items-start justify-between gap-2.5 [&>div]:grid [&>div]:gap-0.5 [&_h3]:[font-size:var(--vui-font-md)] [&_p]:[font-size:var(--vui-font-2xs)] [&_p]:text-[var(--fg-secondary)]",
  headingActions: "flex shrink-0 flex-wrap items-center justify-end gap-2",
  messageList: "grid gap-[9px]",
  messageCard:
    "grid gap-1.5 rounded-[var(--vui-radius-panel-soft)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-card)] p-3 [&_p]:[font-size:var(--vui-font-xs)] [&_p]:leading-[1.5]",
  messageMeta:
    "flex flex-wrap items-center gap-x-3 gap-y-1 [font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)]",
  digestGrid: "grid gap-[9px]",
  digestCard:
    "grid gap-1.5 rounded-[var(--vui-radius-panel-soft)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-card)] p-3 [&>span]:[font-size:var(--vui-font-2xs)] [&>span]:font-[650] [&>span]:tracking-[0.02em] [&>span]:text-[var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-2xs)] [&_p]:leading-[1.5]",
  digestList: "m-0 grid gap-[3px] pl-[18px] [font-size:var(--vui-font-2xs)] leading-[1.5]",
  decisionList:
    "grid gap-1.5 [&>div]:flex [&>div]:flex-wrap [&>div]:items-center [&>div]:gap-2 [&>div]:rounded-[var(--vui-radius-control)] [&>div]:bg-[var(--vui-surface-inset)] [&>div]:p-2 [&_code]:wrap-anywhere [&_code]:[font-size:var(--vui-font-2xs)] [&_code]:text-[var(--fg-secondary)]",
  actions: "flex flex-wrap items-center gap-2",
  hint: "m-0 [font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)]",
};

export default styles;
