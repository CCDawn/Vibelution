const styles = {
  trigger: "!inline-flex !h-7 !min-h-7 !w-auto !max-w-full !items-center !gap-1 !rounded-full !border-0 !bg-transparent !px-1.5 !py-0 !text-vui-xs !font-medium !tracking-[-0.01em] !text-[var(--fg-secondary)] !shadow-none hover:!bg-[var(--vui-control-muted)] hover:!text-[var(--fg-primary)] focus-visible:!ring-2 focus-visible:!ring-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] data-[open=true]:!bg-[var(--vui-control-muted)] data-[open=true]:!text-[var(--fg-primary)]",
  label: "max-w-[min(16rem,38vw)] min-w-0 truncate whitespace-nowrap",
  chevron: "shrink-0 opacity-55",
} as const;

export default styles;
