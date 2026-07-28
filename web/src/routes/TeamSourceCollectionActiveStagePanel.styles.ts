import {
  vuiFlatPanelClass,
  vuiStateSelectedRowClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  sourceCollectionExtractionPanels:
    "sourceCollectionExtractionPanels min-w-0 flex h-full min-h-0 flex-col content-start gap-2 overflow-auto [scrollbar-gutter:stable] max-[1020px]:h-auto max-[1020px]:overflow-visible",
  sourceCollectionIngestionPanels:
    "sourceCollectionIngestionPanels min-w-0 grid min-h-0 content-stretch gap-2 grid-rows-[auto_minmax(0,1fr)] overflow-hidden max-[860px]:min-h-[560px] max-[860px]:grid-rows-[auto_minmax(0,1fr)] max-[860px]:overflow-hidden",
  sourceCollectionStageChatActions:
    "sourceCollectionStageChatActions min-w-0 !grid grid-cols-[repeat(2,minmax(0,1fr))] items-center gap-1.5 [&_a]:inline-flex [&_a]:w-full [&_a]:max-w-full [&_a]:items-center [&_a]:justify-center [&_a]:gap-1.5 [&_a]:min-h-[30px] [&_a]:px-2 [&_a]:rounded-[7px] [&_a]:border [&_a]:border-[color:color-mix(in_srgb,var(--accent-cool)_36%,var(--border-soft))] [&_a]:bg-[var(--vui-surface-row)] [&_a]:text-[var(--fg-primary)] [&_a]:font-[760] [&_a]:no-underline [&_a]:whitespace-nowrap [&_[data-vui=native-button]]:min-h-[30px] [&_[data-vui=native-button]]:w-full [&_[data-vui=native-button]]:max-w-full [&_[data-vui=native-button]:first-child]:col-span-2 max-[1020px]:grid-cols-[repeat(3,max-content)] max-[1020px]:justify-start max-[1020px]:[&_[data-vui=native-button]]:w-fit max-[1020px]:[&_a]:w-fit max-[1020px]:[&_[data-vui=native-button]:first-child]:col-span-1",
  sourceCollectionStageErrors:
    "sourceCollectionStageErrors min-w-0 col-start-2 row-start-2 grid min-h-0 content-start gap-1.5 overflow-auto empty:hidden max-[1020px]:col-start-1 max-[1020px]:row-start-2 max-[1020px]:overflow-visible",
  sourceCollectionStageHandoff:
    "sourceCollectionStageHandoff min-w-0 grid gap-0.5 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-secondary)] [&>span]:min-w-0 [&>span]:grid [&>span]:grid-cols-[minmax(64px,0.7fr)_minmax(0,1fr)] [&>span]:gap-2 [&>span]:break-words [&>span]:[overflow-wrap:anywhere] [&>span]:border-b [&>span]:border-[var(--vui-border-subtle)] [&>span]:py-1.5 [&>span:last-child]:border-b-0 [&_b]:text-[var(--fg-tertiary)]",
  sourceCollectionStageHandoffNext:
    "sourceCollectionStageHandoffNext min-w-0 text-[var(--fg-primary)]",
  sourceCollectionStagePrimaryAction:
    `sourceCollectionStagePrimaryAction min-w-0 flex w-fit max-w-full flex-wrap items-center justify-center gap-1.5 ${vuiStateSelectedRowClass}`,
  sourceCollectionStageResult:
    "sourceCollectionStageResult min-w-0 col-start-1 row-start-1 row-span-2 grid h-full min-h-0 overflow-hidden max-[1020px]:col-start-1 max-[1020px]:row-start-3 max-[1020px]:row-span-1 max-[1020px]:h-auto max-[1020px]:min-h-[560px] max-[1020px]:overflow-visible",
  sourceCollectionStageSecondaryAction:
    "sourceCollectionStageSecondaryAction min-w-0 flex flex-wrap items-center gap-1.5 w-fit max-w-full",
  sourceCollectionStageWorkspace:
    "sourceCollectionStageWorkspace min-w-0 !grid h-full min-h-[360px] max-w-full content-stretch gap-[var(--team-workbench-gap)] p-0 grid-cols-[minmax(0,1fr)_clamp(270px,17vw,338px)] grid-rows-[auto_minmax(0,1fr)] overflow-hidden max-[1020px]:!h-auto max-[1020px]:min-h-[775px] max-[1020px]:grid-cols-[minmax(0,1fr)] max-[1020px]:grid-rows-[auto_auto_auto] max-[1020px]:overflow-visible",
  sourceCollectionStageWorkspaceCompact:
    "sourceCollectionStageWorkspace sourceCollectionStageWorkspaceCompact min-w-0 !grid h-full min-h-0 max-w-full content-stretch gap-[var(--team-workbench-gap)] p-0 grid-cols-[minmax(0,1fr)_clamp(270px,17vw,338px)] grid-rows-[auto_minmax(0,1fr)] overflow-hidden max-[1020px]:h-auto max-[1020px]:min-h-[775px] max-[1020px]:grid-cols-[minmax(0,1fr)] max-[1020px]:grid-rows-[auto_auto_auto] max-[1020px]:overflow-visible",
  sourceCollectionStageWorkspaceHeader: `sourceCollectionStageWorkspaceHeader min-w-0 col-start-2 row-start-1 !grid grid-cols-[minmax(0,1fr)] content-start items-start gap-2 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] ${vuiFlatPanelClass} p-2 max-[1020px]:col-start-1 max-[1020px]:row-start-1 [&>div]:min-w-0 [&>div:first-child]:grid [&>div:first-child]:gap-0.5 [&>div>strong]:min-w-0 [&>div>strong]:truncate [&>div>span]:min-w-0 [&>div>span]:break-words`,
} as const;

export default styles;
