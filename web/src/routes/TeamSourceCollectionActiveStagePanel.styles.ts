const styles = {
  sourceCollectionExtractionPanels:
    "sourceCollectionExtractionPanels min-w-0 grid content-start gap-2 grid-cols-[minmax(0,1fr)]",
  sourceCollectionIngestionPanels:
    "sourceCollectionIngestionPanels min-w-0 grid min-h-0 content-stretch gap-2 grid-rows-[auto_minmax(0,1fr)] overflow-hidden max-[860px]:min-h-[560px] max-[860px]:grid-rows-[auto_minmax(0,1fr)] max-[860px]:overflow-hidden",
  sourceCollectionStageChatActions:
    "sourceCollectionStageChatActions min-w-0 !grid grid-cols-[repeat(3,max-content)] items-center justify-end gap-1.5 max-[720px]:flex max-[720px]:flex-wrap max-[720px]:justify-start [&_a]:inline-flex [&_a]:w-fit [&_a]:max-w-full [&_a]:items-center [&_a]:justify-center [&_a]:gap-1.5 [&_a]:min-h-[30px] [&_a]:px-3 [&_a]:rounded-[7px] [&_a]:border [&_a]:border-[color:color-mix(in_srgb,var(--accent-cool)_36%,var(--border-soft))] [&_a]:bg-[var(--vui-surface-row)] [&_a]:text-[var(--fg-primary)] [&_a]:font-[760] [&_a]:no-underline [&_a]:whitespace-nowrap [&_[data-vui=native-button]]:min-h-[30px] [&_[data-vui=native-button]]:w-fit [&_[data-vui=native-button]]:max-w-full",
  sourceCollectionStageHandoff:
    "sourceCollectionStageHandoff min-w-0 grid gap-1 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-secondary)] [&>span]:min-w-0 [&>span]:break-words [&>span]:[overflow-wrap:anywhere] [&_b]:mr-1 [&_b]:text-[var(--fg-tertiary)]",
  sourceCollectionStageHandoffNext:
    "sourceCollectionStageHandoffNext min-w-0 text-[var(--fg-primary)]",
  sourceCollectionStagePrimaryAction:
    "sourceCollectionStagePrimaryAction min-w-0 flex flex-wrap items-center gap-1.5 border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))] text-[var(--accent-cool)] w-fit max-w-full",
  sourceCollectionStageSecondaryAction:
    "sourceCollectionStageSecondaryAction min-w-0 flex flex-wrap items-center gap-1.5 w-fit max-w-full",
  sourceCollectionStageWorkspace:
    "sourceCollectionStageWorkspace min-w-0 grid h-full min-h-[360px] max-w-full content-stretch gap-[var(--team-workbench-gap)] p-[var(--team-workbench-gap)] grid-rows-[auto_minmax(0,1fr)] overflow-hidden max-[760px]:h-auto max-[760px]:min-h-0 max-[760px]:grid-rows-[auto_auto] max-[760px]:overflow-visible",
  sourceCollectionStageWorkspaceHeader:
    "sourceCollectionStageWorkspaceHeader min-w-0 !grid grid-cols-[minmax(0,1fr)_minmax(260px,0.7fr)_max-content] items-start gap-2 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-2 max-[1180px]:grid-cols-[minmax(0,1fr)_auto] max-[760px]:grid-cols-[minmax(0,1fr)] [&>div]:min-w-0 [&>div:first-child]:grid [&>div:first-child]:gap-0.5 [&>div>strong]:min-w-0 [&>div>strong]:truncate [&>div>span]:min-w-0 [&>div>span]:break-words",
} as const;

export default styles;
