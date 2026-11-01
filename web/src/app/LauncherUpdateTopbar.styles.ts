const styles = {
  pageContent: "grid w-full max-w-xl gap-4",
  pageStatus: "text-vui-sm font-semibold",
  pageActions: "flex flex-wrap items-center gap-2",
  failure: "m-0 break-words text-vui-xs leading-relaxed text-[var(--state-error)]",
  versions: "m-0 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 border-y border-vui-border-subtle py-3 text-vui-xs",
  version: "m-0 text-right font-mono",
  metadata: "text-vui-xs text-vui-fg-tertiary",
} as const;

export default styles;
