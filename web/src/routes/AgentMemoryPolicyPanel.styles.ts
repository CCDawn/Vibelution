const styles = {
  fieldSection: "grid min-w-0 gap-4 [&>h3]:m-0 [&>h3]:text-[15px] [&>h3]:font-semibold",
  inlineAdd: "grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2 [&_input]:min-w-0",
  memoryControl: "grid min-w-0 gap-2",
  pendingStatus: "text-sm text-[var(--accent-warm-2)]",
  policyIdValue: "min-w-0 [overflow-wrap:anywhere] text-sm text-vui-fg-primary focus-visible:outline-2 focus-visible:outline-vui-accent-cool",
  rootPathTooltip: "[overflow-wrap:anywhere] [font-family:var(--font-mono,_ui-monospace,_SFMono-Regular,_Consolas,_monospace)] [font-size:var(--vui-font-xs)]",
  savedStatus: "text-sm text-vui-fg-secondary",
  selectedValues: "flex min-h-8 min-w-0 flex-wrap items-center gap-1 [&>[data-vui=button]]:!max-w-full [&>[data-vui=button]]:!px-1 [&>[data-vui=button]]:!text-sm [&>[data-vui=button]]:![background:transparent] [&>[data-vui=button]]:!text-vui-fg-secondary",
} as const;

export default styles;
