import {
  vuiFlatPanelClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  sourceCollectionFocusedPanel:
    "sourceCollectionFocusedPanel min-w-0 rounded-none border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-2 grid grid-cols-[minmax(0,1fr)_clamp(320px,26vw,420px)] isolate gap-2 auto-rows-min max-[960px]:grid-cols-[minmax(0,1fr)] [&>*]:min-w-0",
  workflowSourceCollectionDetails: `workflowSourceCollectionDetails min-w-0 grid min-h-0 content-start gap-1.5 overflow-hidden ${vuiFlatPanelClass} p-2 [&>summary]:grid [&>summary]:cursor-pointer [&>summary]:list-none [&>summary]:grid-cols-[minmax(0,1fr)_auto] [&>summary]:items-center [&>summary]:gap-2 [&>summary_span]:min-w-0 [&>summary_span]:truncate [&>summary_small]:whitespace-nowrap [&>summary_small]:text-[var(--fg-tertiary)]`,
} as const;

export default styles;
