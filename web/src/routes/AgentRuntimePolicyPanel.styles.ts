const styles = {
  contextModes: "flex min-w-0 flex-wrap items-center gap-4",
  errorText: "m-0 min-w-0 whitespace-pre-wrap break-words text-sm text-[var(--state-error)]",
  fieldSection: "grid min-w-0 content-start gap-4 [&>h3]:m-0 [&>h3]:text-[15px] [&>h3]:font-semibold",
  pendingStatus: "text-sm text-[var(--accent-warm-2)]",
  policyMeta: "grid min-w-0 gap-1 text-xs",
  policyMetaTrigger: "cursor-help rounded-sm focus-visible:outline-2 focus-visible:outline-vui-accent-cool",
  savedStatus: "text-sm text-vui-fg-secondary",
  successText: "m-0 min-w-0 whitespace-pre-wrap break-words text-sm text-vui-fg-secondary",
} as const;

export default styles;
