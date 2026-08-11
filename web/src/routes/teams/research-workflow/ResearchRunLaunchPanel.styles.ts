export default {
  root: "flex h-full min-h-0 flex-col gap-3 overflow-auto p-3",
  contract: "font-mono text-xs",
  error: "text-sm text-[var(--state-error)]",
  actions: "flex justify-end gap-2",
  advancedContract: "rounded-[var(--vui-radius-panel-soft)] border border-vui-border-subtle bg-vui-surface-inset",
  advancedContractSummary: "cursor-pointer list-none px-3 py-2 text-sm font-medium text-vui-fg-secondary [&::-webkit-details-marker]:hidden",
  advancedContractBody: "border-t border-vui-border-subtle p-3",
} as const;
