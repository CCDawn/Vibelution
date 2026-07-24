import {
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  panelEyebrow:
    "panelEyebrow min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  pipelineBoundary: "pipelineBoundary min-w-0",
  pipelineHeader:
    "pipelineHeader min-w-0 grid grid-cols-[minmax(0,1fr)] gap-1 [&_h2]:truncate",
  pipelineIndex:
    "pipelineIndex inline-grid h-5 w-5 shrink-0 place-items-center rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] [font-size:var(--vui-font-xs)] font-semibold text-[var(--fg-tertiary)]",
  pipelinePanel: `pipelinePanel min-w-0 ${vuiFlatPanelClass} p-2 !grid grid-cols-[minmax(128px,0.2fr)_minmax(0,1fr)] items-start gap-2 max-[760px]:grid-cols-[1fr]`,
  pipelineStep: `pipelineStep min-w-0 grid grid-cols-[auto_auto_minmax(0,1fr)] items-center gap-1 ${vuiOpaqueRowClass} px-1.5 py-1 [&>strong]:tabular-nums [&>span:last-child]:truncate`,
  pipelineSteps:
    "pipelineSteps min-w-0 grid grid-cols-[repeat(5,minmax(0,1fr))] gap-1 max-[920px]:grid-cols-[repeat(auto-fit,minmax(min(100%,8rem),1fr))] max-[520px]:grid-cols-[1fr]",
  summaryCard: `summaryCard min-w-0 ${vuiOpaqueRowClass} grid min-h-[54px] grid-cols-[minmax(0,1fr)_auto] items-center gap-2 px-2 py-1.5 [&>span]:[font-size:var(--vui-font-xs)] [&>strong]:[font-size:var(--vui-font-title)]`,
  summaryGrid: `summaryGrid min-w-0 ${vuiFlatPanelClass} p-2 grid gap-1.5 grid-cols-[repeat(auto-fit,minmax(min(100%,9rem),1fr))]`,
} as const;

export default styles;
