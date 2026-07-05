const styles = {
  sourceCollectionConversationHeader:
    "sourceCollectionConversationHeader min-w-0 flex flex-wrap items-center gap-1.5",
  sourceCollectionConversationPanel:
    "sourceCollectionConversationPanel min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-[var(--team-workbench-gap)] grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)] content-stretch gap-[var(--team-workbench-gap)] overflow-hidden",
  sourceCollectionResultWarning:
    "sourceCollectionResultWarning min-w-0 border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
  sourceCollectionResultsHeader:
    "sourceCollectionResultsHeader min-w-0 flex flex-wrap items-center gap-1.5",
  sourceCollectionResultsPanel:
    "sourceCollectionResultsPanel min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-[var(--team-workbench-gap)] !flex min-h-0 flex-col gap-[var(--team-workbench-gap)] overflow-hidden max-[760px]:min-h-0",
} as const;

export default styles;
