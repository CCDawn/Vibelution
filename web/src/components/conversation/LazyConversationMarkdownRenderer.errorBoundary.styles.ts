const styles = {
  fallbackText: "m-0 whitespace-pre-wrap break-words [overflow-wrap:anywhere]",
  fallbackPre: "m-0 whitespace-pre-wrap break-words [overflow-wrap:anywhere]",
  // Error-boundary fallback: subtle bordered box holding the raw markdown.
  errorBox:
    "rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-row/60 p-3",
  errorNote: "m-0 mt-2 text-vui-xs text-[var(--fg-tertiary)]",
} as const;

export default styles;
