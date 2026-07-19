const styles = {
  phaseCloseGateAction:
    "phaseCloseGateAction inline-flex w-fit max-w-full items-center gap-1.5 self-start [font-size:var(--vui-font-xs)] font-[760]",
  phaseCloseGateFacts:
    "phaseCloseGateFacts min-w-0 flex flex-wrap items-center gap-1.5 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_span]:inline-flex [&_span]:min-w-0 [&_span]:max-w-full [&_span]:items-center [&_span]:gap-1 [&_span]:rounded-[7px] [&_span]:border [&_span]:border-[color:var(--border-soft)] [&_span]:bg-[color:var(--source-workbench-card)] [&_span]:px-2 [&_span]:py-1 [&_strong]:min-w-0 [&_strong]:truncate [&_strong]:text-[var(--fg-primary)]",
  phaseCloseGateHeader:
    "phaseCloseGateHeader min-w-0 !grid grid-cols-[minmax(0,1fr)_auto] items-start gap-2 max-[640px]:grid-cols-[minmax(0,1fr)] [&>div]:min-w-0 [&_strong]:block [&_strong]:text-[var(--fg-primary)] [&_span]:min-w-0 [&_span]:break-words [&_span]:[overflow-wrap:anywhere]",
  phaseCloseGatePanel:
    "phaseCloseGatePanel min-w-0 grid content-start gap-2 rounded-[var(--radius-panel)] border border-[color:color-mix(in_srgb,var(--accent-cool)_28%,var(--border-soft))] bg-[color:var(--source-workbench-panel)] px-2.5 py-2",
  phaseCloseGateReasons:
    "phaseCloseGateReasons min-w-0 grid gap-1 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-secondary)] [&_span]:min-w-0 [&_span]:break-words [&_span]:[overflow-wrap:anywhere]",
  phaseCloseGateTag:
    "phaseCloseGateTag inline-flex min-h-6 w-fit max-w-full items-center gap-1 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 [font-size:var(--vui-font-xs)] font-[760] leading-none text-[var(--fg-secondary)]",
  phaseCloseGateTagNeutral:
    "phaseCloseGateTagNeutral min-w-0",
  phaseCloseGateTagSuccess:
    "phaseCloseGateTagSuccess min-w-0 border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]",
  phaseCloseGateTagWarning:
    "phaseCloseGateTagWarning min-w-0 border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
} as const;

export default styles;
