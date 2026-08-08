const styles = {
  panel: "flex h-full min-h-0 flex-col gap-3 overflow-auto p-3",
  detailGrid: "m-0 grid grid-cols-[88px_1fr] gap-x-2 gap-y-2 text-sm",
  dt: "text-[var(--fg-tertiary)]",
  dd: "m-0 text-[var(--fg-primary)]",
  ddBreak: "m-0 break-all text-[var(--fg-primary)]",
  description: "m-0 text-sm text-[var(--fg-secondary)]",
} as const;

export default styles;
