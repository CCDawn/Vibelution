const styles = {
  sourceCollectionPageBody:
    "sourceCollectionPageBody min-w-0 w-full max-w-none flex-1 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] !grid h-full min-h-0 grid-cols-[clamp(300px,20vw,348px)_minmax(520px,1fr)_clamp(270px,17vw,338px)] grid-rows-[auto_minmax(0,1fr)] content-stretch gap-[var(--team-workbench-gap)] overflow-hidden p-[var(--team-workbench-gap)] [&>[data-vui-product=team-stage-command-bar]]:col-span-3 [&>[data-vui-product=team-stage-command-bar]]:col-start-1 [&>[data-vui-product=team-stage-command-bar]]:row-start-1 max-[1020px]:h-auto max-[1020px]:grid-cols-[minmax(0,1fr)] max-[1020px]:grid-rows-[auto_auto_auto] max-[1020px]:overflow-auto max-[1020px]:[&>[data-vui-product=team-stage-command-bar]]:col-span-1",
  sourceCollectionPageBodyCompact:
    "sourceCollectionPageBody sourceCollectionPageBodyCompact min-w-0 w-full max-w-none flex-1 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] !grid h-full min-h-0 grid-cols-[clamp(300px,20vw,348px)_minmax(520px,1fr)_clamp(270px,17vw,338px)] grid-rows-[auto_minmax(0,1fr)] content-stretch gap-[var(--team-workbench-gap)] overflow-hidden p-[var(--team-workbench-gap)] [&>*]:min-w-0 [&>[data-vui-product=team-stage-command-bar]]:col-span-3 [&>[data-vui-product=team-stage-command-bar]]:col-start-1 [&>[data-vui-product=team-stage-command-bar]]:row-start-1 max-[1020px]:h-auto max-[1020px]:grid-cols-[minmax(0,1fr)] max-[1020px]:grid-rows-[auto_auto_auto] max-[1020px]:overflow-auto max-[1020px]:[&>[data-vui-product=team-stage-command-bar]]:col-span-1",
  sourceCollectionPageGrid:
    "sourceCollectionPageGrid min-w-0 grid h-full min-h-0 max-w-full content-stretch gap-[var(--team-workbench-gap)] col-start-2 col-span-2 row-start-2 grid-cols-[minmax(0,1fr)] overflow-hidden max-[1020px]:col-start-1 max-[1020px]:col-span-1 max-[1020px]:row-start-3 max-[1020px]:!h-auto max-[1020px]:overflow-visible",
  sourceCollectionPageGridCompact:
    "sourceCollectionPageGrid sourceCollectionPageGridCompact min-w-0 grid h-full min-h-0 max-w-full content-stretch gap-[var(--team-workbench-gap)] col-start-2 col-span-2 row-start-2 grid-cols-[minmax(0,1fr)] overflow-hidden max-[1020px]:col-start-1 max-[1020px]:col-span-1 max-[1020px]:row-start-3 max-[1020px]:h-auto max-[1020px]:overflow-visible",
  sourceCollectionLeftRail:
    "sourceCollectionLeftRail col-start-1 row-start-2 grid min-h-0 min-w-0 content-start gap-[var(--team-workbench-gap)] overflow-y-auto overflow-x-hidden pr-0.5 [&>[data-vui-product=team-stage-pipeline]]:grid-cols-[minmax(0,1fr)] [&>[data-vui-product=team-stage-pipeline]]:content-start max-[1020px]:row-start-2 max-[1020px]:overflow-visible max-[1020px]:pr-0",
  sourceCollectionRunContext:
    "sourceCollectionRunContext min-w-0 grid content-start gap-2 pt-1 [&_.sourceCollectionRunSwitcher]:!grid-cols-[minmax(0,1fr)] [&_.sourceCollectionRunSwitcherMain]:!grid-cols-[minmax(0,1fr)] [&_.sourceCollectionRunSwitcherStats]:!grid [&_.sourceCollectionRunSwitcherStats]:grid-cols-[repeat(2,minmax(0,1fr))] [&_.sourceCollectionRunSwitcherStats]:justify-stretch [&_.sourceCollectionRunSwitcherStats_span]:!whitespace-normal",
  sourceCollectionRunHistory:
    "sourceCollectionRunHistory min-w-0 rounded-[var(--radius-panel)] border border-[color:var(--border-soft)] bg-[color:var(--source-workbench-panel)] px-2.5 py-1.5 [&>summary]:cursor-pointer [&>summary]:py-1 [&>summary]:[font-size:var(--vui-font-xs)] [&>summary]:font-[720] [&>summary]:text-[var(--fg-secondary)]",
} as const;

export default styles;
