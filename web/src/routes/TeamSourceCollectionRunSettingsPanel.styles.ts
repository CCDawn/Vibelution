const styles = {
  workflowSourceCollectionDetails:
    "workflowSourceCollectionDetails min-w-0",
  workflowSourceCollectionForm:
    "workflowSourceCollectionForm min-w-0 grid gap-1 text-[var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full !grid grid-cols-[repeat(2,minmax(0,1fr))] gap-[5px]",
  workflowSourceCollectionWide:
    "workflowSourceCollectionWide min-w-0",
} as const;

export default styles;
