const styles = {
  // A recovery note is transcript chrome, not a log line. It reads as one
  // quiet annotation: a soft tinted block, no border, the task quote on its
  // own indented line, and the timestamp pushed to the end of the header.
  row: "vui-components-conversationview cliAgentLifecycleTurn sessionRecoveryNotice mx-auto flex w-fit max-w-full min-w-0 flex-col gap-1 rounded-[var(--radius-panel)] bg-[color-mix(in_srgb,var(--accent-cool)_6%,var(--vui-surface-panel))] px-3 py-2 text-vui-sm leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  head: "flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1",
  icon: "inline-flex size-4 shrink-0 items-center justify-center text-[var(--accent-cool)]",
  label: "min-w-0 text-[var(--fg-secondary)]",
  time: "ml-auto shrink-0 whitespace-nowrap text-vui-xs leading-tight text-[var(--fg-tertiary)] tabular-nums",
  detail: "min-w-0 max-w-[56ch] truncate border-l border-[color-mix(in_srgb,var(--accent-cool)_24%,transparent)] pl-2 text-vui-xs leading-relaxed text-[var(--fg-tertiary)]",
} as const;
export default styles;
