const styles = {
  phaseCloseGateAction:
    "phaseCloseGateAction inline-flex w-fit max-w-full items-center gap-1.5 self-start [font-size:var(--vui-font-xs)] font-[760]",
  phaseCloseGateFacts:
    "phaseCloseGateFacts min-w-0 flex flex-wrap items-center gap-1.5 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_span]:inline-flex [&_span]:min-w-0 [&_span]:max-w-full [&_span]:items-center [&_span]:gap-1 [&_span]:rounded-[7px] [&_span]:border [&_span]:border-[color:var(--border-soft)] [&_span]:bg-[color:var(--source-workbench-card)] [&_span]:px-2 [&_span]:py-1 [&_strong]:min-w-0 [&_strong]:truncate [&_strong]:text-[var(--fg-primary)]",
  phaseCloseGateHeader:
    "phaseCloseGateHeader min-w-0 !grid grid-cols-[minmax(0,1fr)_auto] items-start gap-2 max-[640px]:grid-cols-[minmax(0,1fr)] [&>div]:min-w-0 [&_strong]:block [&_strong]:text-[var(--fg-primary)] [&_span]:min-w-0 [&_span]:break-words [&_span]:[overflow-wrap:anywhere]",
  phaseCloseGateEyebrow:
    "mb-0.5 block [font-size:var(--vui-font-xs)] font-[760] uppercase tracking-[0.06em] text-[var(--fg-tertiary)]",
  phaseCloseGatePanel:
    "phaseCloseGatePanel min-w-0 grid content-start gap-2 rounded-[var(--radius-panel)] border border-[color:color-mix(in_srgb,var(--accent-cool)_28%,var(--border-soft))] bg-[color:var(--source-workbench-panel)] px-2.5 py-2",
  phaseCloseGatePanelCompact:
    "phaseCloseGatePanelCompact gap-2.5 !border-[color:var(--border-soft)] !p-3",
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
  phaseCloseGateSteps:
    "phaseCloseGateSteps m-0 grid list-none gap-0 p-0",
  phaseCloseGateStep:
    "relative grid min-h-10 grid-cols-[1.5rem_minmax(0,1fr)] gap-2 [&:not(:last-child)]:after:absolute [&:not(:last-child)]:after:left-[0.72rem] [&:not(:last-child)]:after:top-6 [&:not(:last-child)]:after:h-4 [&:not(:last-child)]:after:w-px [&:not(:last-child)]:after:bg-[color:var(--border-soft)] [&>span]:grid [&>span]:size-6 [&>span]:place-items-center [&>span]:rounded-full [&>span]:border [&>span]:border-[color:var(--border-soft)] [&>span]:bg-[color:var(--source-workbench-card)] [&>span]:[font-size:var(--vui-font-xs)] [&>span]:font-[760] [&>span]:text-[var(--fg-tertiary)] [&>div]:grid [&>div]:content-start [&>div]:gap-0.5 [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:text-[var(--fg-primary)] [&_small]:[font-size:var(--vui-font-xs)] [&_small]:text-[var(--fg-tertiary)]",
  phaseCloseGateStepCurrent:
    "relative grid min-h-10 grid-cols-[1.5rem_minmax(0,1fr)] gap-2 [&:not(:last-child)]:after:absolute [&:not(:last-child)]:after:left-[0.72rem] [&:not(:last-child)]:after:top-6 [&:not(:last-child)]:after:h-4 [&:not(:last-child)]:after:w-px [&:not(:last-child)]:after:bg-[color:var(--border-soft)] [&>span]:grid [&>span]:size-6 [&>span]:place-items-center [&>span]:rounded-full [&>span]:border [&>span]:border-[color:var(--accent-cool)] [&>span]:bg-[color:color-mix(in_srgb,var(--accent-cool)_10%,transparent)] [&>span]:[font-size:var(--vui-font-xs)] [&>span]:font-[760] [&>span]:text-[var(--accent-cool)] [&>div]:grid [&>div]:content-start [&>div]:gap-0.5 [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:text-[var(--fg-primary)] [&_small]:[font-size:var(--vui-font-xs)] [&_small]:font-[720] [&_small]:text-[var(--accent-cool)]",
  phaseCloseGateStepDone:
    "relative grid min-h-10 grid-cols-[1.5rem_minmax(0,1fr)] gap-2 [&:not(:last-child)]:after:absolute [&:not(:last-child)]:after:left-[0.72rem] [&:not(:last-child)]:after:top-6 [&:not(:last-child)]:after:h-4 [&:not(:last-child)]:after:w-px [&:not(:last-child)]:after:bg-[color:var(--border-soft)] [&>span]:grid [&>span]:size-6 [&>span]:place-items-center [&>span]:rounded-full [&>span]:border [&>span]:border-[color:var(--state-success)] [&>span]:bg-[color:var(--state-success)] [&>span]:text-white [&>div]:grid [&>div]:content-start [&>div]:gap-0.5 [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:text-[var(--fg-primary)] [&_small]:[font-size:var(--vui-font-xs)] [&_small]:text-[var(--state-success)]",
  phaseCloseGateRuntimeDetails:
    "phaseCloseGateRuntimeDetails border-t border-[color:var(--border-soft)] pt-1 [&>summary]:cursor-pointer [&>summary]:py-1.5 [&>summary]:[font-size:var(--vui-font-xs)] [&>summary]:font-[720] [&>summary]:text-[var(--fg-secondary)] [&_dl]:m-0 [&_dl]:grid [&_dl]:gap-1.5 [&_dl]:pt-1 [&_dl_div]:grid [&_dl_div]:grid-cols-[4.25rem_minmax(0,1fr)] [&_dl_div]:gap-2 [&_dt]:[font-size:var(--vui-font-xs)] [&_dt]:text-[var(--fg-tertiary)] [&_dd]:m-0 [&_dd]:min-w-0 [&_dd]:break-words [&_dd]:[font-size:var(--vui-font-xs)] [&_dd]:text-[var(--fg-secondary)]",
} as const;

export default styles;
