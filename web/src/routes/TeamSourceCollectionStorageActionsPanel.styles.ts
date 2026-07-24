import {
  vuiStateDangerSoftClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  workflowSourceCollectionStorageActions:
    "workflowSourceCollectionStorageActions min-w-0 !grid grid-cols-[minmax(0,1fr)_auto] items-start gap-2 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[color:var(--source-workbench-card)] p-1.5 [font-size:var(--vui-font-xs)] max-[760px]:grid-cols-[1fr] [&>div:first-child]:min-w-0 [&>div:first-child_strong]:text-[var(--fg-primary)]",
  workflowSourceCollectionStorageButtons:
    "workflowSourceCollectionStorageButtons min-w-0 flex flex-wrap items-center justify-end gap-1.5 max-[760px]:justify-start [&_[data-vui=native-button]]:w-fit [&_[data-vui=native-button]]:max-w-full [&_[data-vui=native-button]]:min-h-[26px] [&_[data-vui=native-button]]:px-2",
  workflowSourceCollectionStorageDetails:
    "workflowSourceCollectionStorageDetails min-w-0 col-span-2 grid gap-1 max-[760px]:col-span-1 [&_summary]:inline-flex [&_summary]:w-fit [&_summary]:cursor-pointer [&_summary]:items-center [&_summary]:gap-1.5 [&_summary]:font-[780] [&_small]:block [&_small]:min-w-0 [&_small]:truncate [&_small]:text-[var(--fg-muted)]",
  workflowSourceCollectionStorageError:
    `workflowSourceCollectionStorageError min-w-0 ${vuiStateDangerSoftClass}`,
} as const;

export default styles;
