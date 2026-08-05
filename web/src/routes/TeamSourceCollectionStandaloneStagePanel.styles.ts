const styles = {
  /** Outer shell: command bar + resizable left/main (stage panel owns center/right). */
  sourceCollectionPageBody:
    "sourceCollectionPageBody min-w-0 w-full max-w-none flex h-full min-h-0 flex-1 flex-col gap-[var(--team-workbench-gap)] overflow-hidden p-[var(--team-workbench-gap)] [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  sourceCollectionPageBodyCompact:
    "sourceCollectionPageBody sourceCollectionPageBodyCompact min-w-0 w-full max-w-none flex h-full min-h-0 flex-1 flex-col gap-[var(--team-workbench-gap)] overflow-hidden p-[var(--team-workbench-gap)] [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] [&>*]:min-w-0",
  sourceCollectionPageSplit:
    "sourceCollectionPageSplit min-h-0 min-w-0 flex-1",
  sourceCollectionLeftRail:
    "sourceCollectionLeftRail grid h-full min-h-0 min-w-0 content-start gap-[var(--team-workbench-gap)] overflow-y-auto overflow-x-hidden p-0.5 [&>[data-vui-product=team-stage-pipeline]]:grid-cols-[minmax(0,1fr)] [&>[data-vui-product=team-stage-pipeline]]:content-start",
  sourceCollectionMainHost:
    "sourceCollectionMainHost flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden",
  sourceCollectionRunContext:
    "sourceCollectionRunContext min-w-0 grid content-start gap-2 pt-1 [&_.sourceCollectionRunSwitcher]:!grid-cols-[minmax(0,1fr)] [&_.sourceCollectionRunSwitcherMain]:!grid-cols-[minmax(0,1fr)] [&_.sourceCollectionRunSwitcherStats]:!grid [&_.sourceCollectionRunSwitcherStats]:grid-cols-[repeat(2,minmax(0,1fr))] [&_.sourceCollectionRunSwitcherStats]:justify-stretch [&_.sourceCollectionRunSwitcherStats_span]:!whitespace-normal",
  sourceCollectionRunHistory:
    "sourceCollectionRunHistory min-w-0 rounded-[var(--radius-panel)] border border-[color:var(--border-soft)] bg-[color:var(--source-workbench-panel)] px-2.5 py-1.5 [&>summary]:cursor-pointer [&>summary]:py-1 [&>summary]:[font-size:var(--vui-font-xs)] [&>summary]:font-[720] [&>summary]:text-[var(--fg-secondary)]",
  /** @deprecated kept for layout-test compatibility aliases during migration */
  sourceCollectionPageGrid:
    "sourceCollectionPageGrid min-w-0 flex h-full min-h-0 flex-1 flex-col overflow-hidden",
  sourceCollectionPageGridCompact:
    "sourceCollectionPageGrid sourceCollectionPageGridCompact min-w-0 flex h-full min-h-0 flex-1 flex-col overflow-hidden",
} as const;

export default styles;
