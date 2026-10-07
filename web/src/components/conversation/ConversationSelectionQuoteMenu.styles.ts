const styles = {
  selectionQuoteMenu:
    "vui-components-conversationview selectionQuoteMenu fixed z-[80] flex min-w-0 w-max max-w-[calc(100vw-24px)] items-center gap-0.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-1 shadow-[var(--vui-shadow-hairline)]",
  selectionQuoteMenuItem:
    "vui-components-conversationview selectionQuoteMenuItem min-w-0 !border-0 !bg-transparent !px-1.5 !shadow-none text-vui-xs font-medium leading-tight !text-[var(--fg-secondary)] hover:!bg-[var(--vui-control-muted)] hover:!text-[var(--fg-primary)]",
} as const;

export default styles;
