export const platformVersionBadgeStyles = {
  wrapper: "flex items-center gap-1.5 whitespace-nowrap text-[12px] leading-none text-[var(--fg-secondary)]",
  version: "font-semibold text-[var(--fg-primary)]",
  build: "text-[var(--vui-control-muted)]",
  progress: "text-[var(--vui-control-muted)]",
  pending: "h-1.5 w-1.5 rounded-full bg-[var(--accent-warm)]",
} as const;
