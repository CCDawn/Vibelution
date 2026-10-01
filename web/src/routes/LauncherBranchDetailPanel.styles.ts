const styles = {
  root: "flex min-h-0 flex-1 flex-col px-7 py-4 max-[640px]:px-4",
  backButton: "mb-4 !px-0",
  headingRow: "mb-5 flex flex-wrap items-start justify-between gap-3",
  heading: "m-0 min-w-0 break-all text-lg font-semibold",
  content: "min-h-0 flex-1 overflow-auto pt-5",
  facts: "m-0 grid grid-cols-[100px_minmax(0,1fr)] gap-x-5 gap-y-4 text-vui-sm",
  fact: "contents",
  factLabel: "text-vui-fg-secondary",
  factValue: "m-0 break-all",
  startup: "space-y-4 text-vui-sm",
  errorBox: "rounded-md border border-vui-border-subtle p-4",
  errorMessage: "m-0 text-[var(--state-error)]",
  errorCode: "mb-0 mt-2 text-vui-xs text-vui-fg-secondary",
  noError: "text-vui-fg-secondary",
} as const;

export default styles;
