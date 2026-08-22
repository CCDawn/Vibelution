const styles: Record<string, string> = {
  // Lives inside the challenge-cup question detail panel (300–520px inspector),
  // so grids respond to the container, never the viewport.
  section:
    "grid scroll-mt-5 gap-3 rounded-[var(--vui-radius-panel-soft)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-4 [&_h3]:m-0 [&_h4]:m-0 [&_p]:m-0",
  heading:
    "flex items-start justify-between gap-2.5 [&>div]:grid [&>div]:gap-0.5 [&_h3]:[font-size:var(--vui-font-md)] [&_p]:[font-size:var(--vui-font-2xs)] [&_p]:text-[var(--fg-secondary)]",
  roundDisplay: "grid min-w-0 gap-3",
  headingActions: "flex shrink-0 flex-wrap items-center justify-end gap-2",
  messageList: "grid gap-[9px]",
  messageCard:
    "grid gap-1.5 rounded-[var(--vui-radius-panel-soft)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-card)] p-3 [&_p]:[font-size:var(--vui-font-xs)] [&_p]:leading-[1.5]",
  messagePreview:
    "m-0 min-w-0 line-clamp-2 [overflow-wrap:anywhere]",
  messageFull:
    "m-0 min-w-0 whitespace-pre-wrap [overflow-wrap:anywhere]",
  messageMeta:
    "flex flex-wrap items-center gap-x-3 gap-y-1 [font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)]",
  digestGrid: "grid min-w-0 gap-[9px]",
  digestCard:
    "grid min-w-0 gap-1.5 rounded-[var(--vui-radius-panel-soft)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-card)] p-3 [&>span]:[font-size:var(--vui-font-2xs)] [&>span]:font-[650] [&>span]:tracking-[0.02em] [&>span]:text-[var(--fg-secondary)] [&_p]:min-w-0 [&_p]:[font-size:var(--vui-font-2xs)] [&_p]:leading-[1.5] [&_p]:[overflow-wrap:anywhere]",
  digestList:
    "m-0 grid min-w-0 gap-[3px] pl-[18px] [font-size:var(--vui-font-2xs)] leading-[1.5] [&_li]:min-w-0 [&_li]:[overflow-wrap:anywhere]",
  proposedCandidateList:
    "m-0 grid max-h-[min(48dvh,360px)] min-w-0 list-none gap-1.5 overflow-y-auto overscroll-contain p-0 [scrollbar-gutter:stable]",
  proposedCandidate:
    "min-w-0 rounded-[var(--vui-radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-inset)] px-2.5 py-2 [overflow-wrap:anywhere]",
  decisionList:
    "grid min-w-0 gap-1.5 [&>div]:flex [&>div]:min-w-0 [&>div]:flex-wrap [&>div]:items-center [&>div]:gap-2 [&>div]:rounded-[var(--vui-radius-control)] [&>div]:bg-[var(--vui-surface-inset)] [&>div]:p-2 [&_code]:wrap-anywhere [&_code]:[font-size:var(--vui-font-2xs)] [&_code]:text-[var(--fg-secondary)]",
  actions: "flex flex-wrap items-center gap-2",
  actionFooter:
    "sticky bottom-0 z-10 min-w-0 border-t border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] py-2 backdrop-blur-md",
  hint: "m-0 min-w-0 [font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)] [overflow-wrap:anywhere]",
};

export default styles;
