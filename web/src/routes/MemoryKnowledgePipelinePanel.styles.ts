const styles = {
  panelEyebrow:
    "panelEyebrow min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  pipelineBoundary: "pipelineBoundary min-w-0",
  pipelineHeader: "pipelineHeader min-w-0 flex flex-wrap items-center gap-1.5",
  pipelineIndex: "pipelineIndex min-w-0",
  pipelinePanel:
    "pipelinePanel min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 !grid grid-cols-[minmax(116px,0.18fr)_minmax(0,1fr)] items-center gap-[5px] max-[760px]:grid-cols-[1fr]",
  pipelineStep:
    "pipelineStep min-w-0 grid grid-cols-[auto_auto_minmax(0,1fr)] items-center gap-1 min-w-0 px-[5px] py-0.5 rounded-[7px] border border-[color:color-mix(in_srgb,var(--border-soft)_70%,transparent)] bg-[color:color-mix(in_srgb,var(--surface-card)_74%,transparent)]",
  pipelineSteps:
    "pipelineSteps min-w-0 grid grid-cols-[repeat(5,minmax(0,1fr))] gap-[3px] min-w-0 max-[760px]:grid-cols-[repeat(2,minmax(0,1fr))]",
  summaryCard:
    "summaryCard min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 grid min-h-[54px] grid-cols-[minmax(0,1fr)_auto] items-center gap-2 px-2 py-1.5 [&>span]:text-[var(--vui-font-xs)] [&>strong]:text-[var(--vui-font-title)]",
  summaryGrid:
    "summaryGrid min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 grid gap-2 grid-cols-[repeat(6,minmax(118px,1fr))] gap-1.5 max-[1180px]:grid-cols-3 max-[720px]:grid-cols-2",
} as const;

export default styles;
