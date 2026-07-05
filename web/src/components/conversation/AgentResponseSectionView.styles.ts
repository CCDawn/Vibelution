const styles = {
  responseBody:
    "vui-components-conversationview responseBody min-w-0 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] grid gap-1.5 border-t border-[color-mix(in_srgb,var(--accent-cool)_18%,var(--vui-border-subtle))] bg-transparent px-0 py-1.5 text-[var(--fg-primary)] shadow-none [overflow-wrap:anywhere]",
  responseSection:
    "vui-components-conversationview responseSection min-w-0 grid w-[min(100%,920px)] max-w-full gap-1 border-l border-[color-mix(in_srgb,var(--accent-cool)_22%,var(--vui-border-subtle))] pl-2.5",
  responseToggle:
    "vui-components-conversationview responseToggle min-w-0 max-w-full overflow-hidden !grid !w-full grid-cols-[auto_auto_minmax(0,1fr)] !items-center !justify-start gap-x-1.5 !border-0 !bg-transparent !p-0 !text-left text-[var(--fg-secondary)] !shadow-none hover:!border-transparent hover:!bg-transparent hover:!shadow-none [&_[data-slot=vui-button-content]]:contents [&_[data-slot=vui-button-label]]:contents",
  statusSpinner:
    "vui-components-conversationview statusSpinner min-w-0 animate-spin",
} as const;

export default styles;
