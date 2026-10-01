const styles = {
  toolbar: "z-20 min-h-12 gap-3 border-b border-vui-border-subtle bg-vui-surface-panel px-4 max-[600px]:gap-2 max-[600px]:px-3",
  title: "truncate text-vui-sm font-medium",
  branch: "flex min-w-0 items-center gap-1 border-l border-vui-border-subtle pl-3 text-vui-xs text-vui-fg-tertiary max-[600px]:hidden",
  button: "!min-h-8 !px-3 !text-vui-xs max-[600px]:!min-h-11",
  trigger: "gap-2 whitespace-nowrap",
  popover: "z-50 w-[min(380px,calc(100vw-24px))] max-h-[calc(100dvh-84px)] overflow-y-auto border-vui-border-soft bg-vui-surface-panel p-0 shadow-[var(--vui-shadow-soft)]",
  content: "grid gap-4 p-4",
  description: "m-0 text-vui-xs leading-relaxed text-vui-fg-secondary",
  versions: "m-0 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 border-y border-vui-border-subtle py-3 text-vui-xs",
  version: "m-0 text-right font-mono",
  actions: "flex flex-wrap justify-end gap-2",
  confirmation: "grid gap-3 border-t border-vui-border-subtle pt-3",
  metadata: "text-vui-xs text-vui-fg-tertiary",
} as const;

export default styles;
