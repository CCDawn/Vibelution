const styles = {
  sourceCollectionPageBody:
    "sourceCollectionPageBody min-w-0 w-full max-w-none flex-1 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] !grid h-full min-h-0 grid-rows-[auto_auto_auto_minmax(0,1fr)] content-stretch gap-[var(--team-workbench-gap)] overflow-auto p-[var(--team-workbench-gap)] max-[760px]:grid-rows-[auto_auto_auto_auto] max-[760px]:content-start",
  sourceCollectionPageBodyCompact:
    "sourceCollectionPageBody sourceCollectionPageBodyCompact min-w-0 w-full max-w-none flex-1 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] !flex h-full min-h-0 flex-col items-stretch gap-[var(--team-workbench-gap)] overflow-auto p-[var(--team-workbench-gap)] [&>*]:min-w-0 [&>*]:shrink-0",
  sourceCollectionPageGrid:
    "sourceCollectionPageGrid min-w-0 grid h-full min-h-0 max-w-full content-stretch gap-[var(--team-workbench-gap)] grid-cols-[minmax(0,1fr)] max-[760px]:!flex max-[760px]:!h-auto max-[760px]:flex-col max-[760px]:content-start max-[760px]:overflow-visible",
  sourceCollectionPageGridCompact:
    "sourceCollectionPageGrid sourceCollectionPageGridCompact min-w-0 !flex h-auto min-h-0 shrink-0 max-w-full flex-col content-start gap-[var(--team-workbench-gap)] overflow-visible",
} as const;

export default styles;
