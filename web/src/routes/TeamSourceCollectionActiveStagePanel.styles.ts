const styles = {
  sourceCollectionExtractionPanels:
    "sourceCollectionExtractionPanels min-w-0 grid content-start gap-2 grid-cols-[minmax(0,1fr)]",
  sourceCollectionIngestionPanels:
    "sourceCollectionIngestionPanels min-w-0 grid min-h-0 content-stretch gap-2 grid-rows-[auto_minmax(0,1fr)] overflow-hidden max-[860px]:min-h-[560px] max-[860px]:grid-rows-[auto_minmax(0,1fr)] max-[860px]:overflow-hidden",
  sourceCollectionStageChatActions:
    "sourceCollectionStageChatActions min-w-0 flex flex-wrap items-center gap-1.5 !grid grid-cols-[repeat(3,max-content)] items-center justify-end gap-1.5 min-w-0 max-[720px]:grid-cols-[1fr] [&_a]:inline-flex [&_a]:items-center [&_a]:justify-center [&_a]:gap-1.5 [&_a]:min-h-[30px] [&_a]:w-max [&_a]:max-w-full [&_a]:px-3 [&_a]:rounded-[7px] [&_a]:border [&_a]:border-[color:color-mix(in_srgb,var(--accent-cool)_42%,var(--border-soft))] [&_a]:bg-[image:var(--vui-gradient-route-soft)] [&_a]:bg-[color:var(--source-workbench-card)] [&_a]:text-[var(--fg-primary)] [&_a]:font-[840] [&_a]:no-underline [&_a]:whitespace-nowrap [&_[data-vui=native-button]]:min-h-[30px]",
  sourceCollectionStageHandoff:
    "sourceCollectionStageHandoff min-w-0",
  sourceCollectionStageHandoffNext:
    "sourceCollectionStageHandoffNext min-w-0",
  sourceCollectionStagePrimaryAction:
    "sourceCollectionStagePrimaryAction min-w-0 flex flex-wrap items-center gap-1.5 border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))] text-[var(--accent-cool)] w-fit max-w-full",
  sourceCollectionStageSecondaryAction:
    "sourceCollectionStageSecondaryAction min-w-0 flex flex-wrap items-center gap-1.5 w-fit max-w-full",
  sourceCollectionStageWorkspace:
    "sourceCollectionStageWorkspace min-w-0 grid h-full min-h-[360px] max-w-full content-stretch gap-[var(--team-workbench-gap)] p-[var(--team-workbench-gap)] grid-rows-[auto_minmax(0,1fr)] overflow-hidden max-[760px]:h-auto max-[760px]:min-h-0 max-[760px]:grid-rows-[auto_auto] max-[760px]:overflow-visible",
  sourceCollectionStageWorkspaceHeader:
    "sourceCollectionStageWorkspaceHeader min-w-0 !grid grid-cols-[minmax(0,1fr)_minmax(260px,0.7fr)_max-content] items-start gap-2 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[color:var(--source-workbench-card)] p-2 max-[1180px]:grid-cols-[minmax(0,1fr)_auto] max-[760px]:grid-cols-[1fr] [&>div]:min-w-0",
} as const;

export default styles;
