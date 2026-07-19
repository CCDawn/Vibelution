const styles = {
  graphCanvasFallback:
    "graphCanvasFallback min-w-0 grid min-h-0 gap-2 p-2",
  graphCanvasLabels:
    "graphCanvasLabels min-w-0 grid min-h-0 gap-2 p-2",
  graphCanvasMount:
    "graphCanvasMount min-w-0 grid min-h-0 gap-2 p-2",
  graphCanvasShell:
    "graphCanvasShell min-w-0 grid h-full min-h-0 content-start overflow-hidden text-[var(--fg-primary)] gap-2 p-2 min-h-[360px] bg-[var(--vui-gradient-route-soft)] after:content-[''] after:[background-size:91px_91px]",
  graphNodeBadge:
    "graphNodeBadge min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 [font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)] data-[detail=true]:z-10 data-[agent-category=session_agent]:border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] data-[agent-category=team_member_agent]:border-[color-mix(in_srgb,var(--accent-warm)_34%,transparent)] data-[node-type=knowledge_base]:border-[color-mix(in_srgb,var(--state-success)_32%,transparent)]",
  graphNodeBadgeQuestion:
    "graphNodeBadgeQuestion min-w-0",
  graphNodeBadgeType:
    "graphNodeBadgeType min-w-0",
} as const;

export default styles;
