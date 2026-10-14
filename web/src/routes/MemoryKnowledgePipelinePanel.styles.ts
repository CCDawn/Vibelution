const styles = {
  pipelineDisclosure: "pipelineDisclosure shrink-0 min-w-0 px-3 pb-2 text-vui-2xs text-vui-fg-secondary [&>summary]:w-fit [&>summary]:cursor-pointer [&>summary]:py-1",
  panelEyebrow:
    "panelEyebrow min-w-0 text-vui-2xs font-normal leading-relaxed text-vui-fg-tertiary",
  pipelineBoundary: "pipelineBoundary min-w-0",
  pipelineHeader:
    "pipelineHeader grid min-w-0 grid-cols-[minmax(0,1fr)] gap-1 [&_h2]:truncate [&_h2]:text-vui-xs [&_h2]:font-medium",
  pipelineIndex:
    "pipelineIndex inline-grid h-5 w-5 shrink-0 place-items-center rounded-full bg-[var(--vui-control-muted)] text-vui-2xs font-medium text-vui-fg-tertiary",
  pipelinePanel:
    "pipelinePanel min-w-0 border-b border-vui-border-subtle bg-transparent py-2 !grid grid-cols-[minmax(128px,0.2fr)_minmax(0,1fr)] items-start gap-3 text-vui-xs max-[760px]:grid-cols-[1fr]",
  pipelineStep:
    "pipelineStep grid min-w-0 grid-cols-[auto_auto_minmax(0,1fr)] items-center gap-1.5 rounded-[var(--radius-control)] bg-vui-surface-row px-2 py-1.5 text-vui-xs [&>strong]:font-medium [&>strong]:tabular-nums [&>span:last-child]:truncate",
  pipelineSteps:
    "pipelineSteps min-w-0 grid grid-cols-[repeat(5,minmax(0,1fr))] gap-1 max-[920px]:grid-cols-[repeat(auto-fit,minmax(min(100%,8rem),1fr))] max-[520px]:grid-cols-[1fr]",
  summaryCard:
    "summaryCard flex min-w-0 items-center justify-between gap-2 py-2 text-vui-xs [&>strong]:text-vui-micro-13 [&>strong]:font-medium",
  summaryGrid: "summaryGrid min-w-0 shrink-0 px-3 [&>section]:!rounded-none [&>section]:!border-0 [&>section]:!bg-transparent [&>section]:!shadow-none [&_[data-vui=metric-strip]]:!rounded-none [&_[data-vui=metric-strip]]:!border-0 [&_[data-vui=metric-strip]]:!bg-transparent",
} as const;

export default styles;
