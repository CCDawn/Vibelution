import {
  vuiFlatPanelClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  sourceCollectionControlPanel: `sourceCollectionControlPanel min-w-0 ${vuiFlatPanelClass} p-2 !grid grid-cols-[minmax(0,1fr)] content-start gap-1.5 [&>*]:min-w-0`,
  workflowIngestionHeader:
    "workflowIngestionHeader min-w-0 !grid grid-cols-[minmax(0,1fr)_auto] items-start gap-2 max-[520px]:grid-cols-[minmax(0,1fr)] [&>div]:min-w-0 [&_strong]:block [&_strong]:truncate [&_span]:min-w-0 [&_span]:break-words",
  workflowTag:
    "workflowTag min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 truncate rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 [font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
} as const;

export default styles;
