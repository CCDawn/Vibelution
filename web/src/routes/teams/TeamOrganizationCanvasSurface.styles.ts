export default {
  interactiveFrame: "touch-none select-none cursor-grab outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--accent-cool)]",
  panningFrame: "!cursor-grabbing",
  viewControls: "absolute bottom-2 left-2 z-[3] max-w-[calc(100%-1rem)] flex-wrap gap-1 rounded-md border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-1",
  zoomLabel: "px-1 text-vui-2xs tabular-nums text-[var(--fg-tertiary)]",
  title: "min-w-0 truncate text-vui-xs font-semibold leading-5",
  secondary: "min-w-0 truncate text-vui-2xs leading-5 text-[var(--fg-tertiary)]",
} as const;
