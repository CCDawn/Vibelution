const styles = {
  sourceCollectionPageBody:
    "sourceCollectionPageBody min-w-0 w-full max-w-none flex-1 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] !grid h-full min-h-0 grid-rows-[auto_auto_auto_minmax(0,1fr)] content-stretch gap-[var(--team-workbench-gap)] overflow-auto p-[var(--team-workbench-gap)] max-[760px]:grid-rows-[auto_auto_auto_auto]",
  sourceCollectionPageGrid:
    "sourceCollectionPageGrid min-w-0 grid h-full min-h-0 max-w-full content-stretch gap-[var(--team-workbench-gap)] grid-cols-[minmax(0,1fr)] max-[760px]:content-start",
} as const;

export default styles;
