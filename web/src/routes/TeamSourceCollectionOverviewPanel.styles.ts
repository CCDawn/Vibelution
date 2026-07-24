import {
  vuiFlatPanelClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  empty:
    "empty min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  messageError:
    "messageError min-w-0 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)] [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  messageResult:
    "messageResult min-w-0 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  workflowIngestionBoundary:
    "workflowIngestionBoundary min-w-0",
  workflowIngestionHeader:
    "workflowIngestionHeader min-w-0 flex flex-wrap items-center gap-1.5",
  workflowSourceCollectionPanel: `workflowSourceCollectionPanel min-w-0 ${vuiFlatPanelClass} p-2`,
  workflowSourceCollectionPlan:
    "workflowSourceCollectionPlan min-w-0",
  workflowSourceCollectionStats:
    "workflowSourceCollectionStats min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  workflowTag:
    "workflowTag min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 [font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
} as const;

export default styles;
