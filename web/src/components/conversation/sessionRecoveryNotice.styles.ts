const styles = {
  // A recovery note is transcript chrome, not a log line: it stays on the
  // transcript measure but sizes to its content, so it reads as one quiet
  // object instead of a full-width strip of grey text.
  row: "vui-components-conversationview cliAgentLifecycleTurn sessionRecoveryNotice mx-auto flex w-fit max-w-full min-w-0 flex-wrap items-center gap-x-2 gap-y-1 rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--accent-cool)_26%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_7%,var(--vui-surface-panel))] px-2.5 py-1.5 text-vui-sm leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  icon: "inline-flex size-5 shrink-0 items-center justify-center self-center rounded-full bg-[color-mix(in_srgb,var(--accent-cool)_14%,transparent)] text-[var(--accent-cool)]",
  label: "min-w-0 text-[var(--fg-secondary)]",
  detail: "inline-block min-w-0 max-w-[min(100%,32ch)] truncate rounded-[var(--radius-control)] bg-[color-mix(in_srgb,var(--vui-border-subtle)_45%,transparent)] px-1.5 py-0.5 align-middle text-vui-xs leading-tight text-[var(--fg-tertiary)]",
  time: "shrink-0 whitespace-nowrap text-vui-xs leading-tight text-[var(--fg-tertiary)] tabular-nums",
} as const;
export default styles;
