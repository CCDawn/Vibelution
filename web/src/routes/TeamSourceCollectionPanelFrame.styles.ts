import {
  vuiFlatPanelClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  sourceCollectionFocusedPanel:
    "sourceCollectionFocusedPanel min-w-0 border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] ring-2 ring-inset ring-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)] transition-[box-shadow] duration-200",
  workflowSourceCollectionDetails: `workflowSourceCollectionDetails min-w-0 grid min-h-0 content-start gap-1.5 overflow-hidden ${vuiFlatPanelClass} p-2 [&>summary]:grid [&>summary]:cursor-pointer [&>summary]:list-none [&>summary]:grid-cols-[minmax(0,1fr)_auto] [&>summary]:items-center [&>summary]:gap-2 [&>summary_span]:min-w-0 [&>summary_span]:truncate [&>summary_small]:whitespace-nowrap [&>summary_small]:text-[var(--fg-tertiary)]`,
} as const;

export default styles;
