const styles = {
  panel: "min-h-0 flex-1 space-y-6 overflow-auto p-6",
  title: "break-words text-vui-title leading-[1.4] font-medium",
  endpoints: "grid gap-3",
  direction: "flex items-center justify-center gap-2 text-vui-xs leading-5 text-[var(--fg-secondary)]",
  sources: "space-y-3 border-t border-[var(--vui-border-subtle)] pt-5",
  sourceTitle: "text-vui-xs leading-5 font-medium",
  sourceEmpty: "text-vui-xs leading-relaxed text-[var(--fg-secondary)]",
  metadata: "text-vui-2xs leading-4 text-[var(--fg-tertiary)]",
  metadataBody: "mt-3 whitespace-pre-wrap break-words",
} as const;

export default styles;
