const styles = {
  imageDownloadButton:
    "vui-components-conversationview imageDownloadButton inline-flex size-[var(--vui-control-height-sm)] shrink-0 items-center justify-center rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-cool)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--surface-panel)]",
  imagePreviewActions:
    "vui-components-conversationview imagePreviewActions flex shrink-0 items-center gap-1.5",
  imagePreviewCloseButton:
    "vui-components-conversationview imagePreviewCloseButton inline-flex size-[var(--vui-control-height-sm)] shrink-0 items-center justify-center rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] p-0 text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-cool)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--surface-panel)] disabled:cursor-default disabled:opacity-55",
  imagePreviewDialog:
    "vui-components-conversationview imagePreviewDialog grid max-h-[calc(100vh-2rem)] w-[min(100vw-2rem,72rem)] min-w-0 grid-rows-[auto_minmax(0,1fr)] gap-3 overflow-hidden rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--surface-panel)] p-3 shadow-[var(--vui-shadow-floating)]",
  imagePreviewLarge:
    "vui-components-conversationview imagePreviewLarge block max-h-[calc(100vh-8rem)] max-w-full min-w-0 justify-self-center rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] object-contain shadow-[var(--vui-shadow-hairline)]",
  imagePreviewOverlay:
    "vui-components-conversationview imagePreviewOverlay fixed inset-0 z-50 grid min-w-0 place-items-center overflow-y-auto bg-[color-mix(in_srgb,var(--surface-base)_72%,transparent)] p-4 backdrop-blur-sm",
  imagePreviewTitle:
    "vui-components-conversationview imagePreviewTitle min-w-0 truncate text-[var(--vui-font-sm)] font-semibold leading-[var(--vui-line-compact)] text-[var(--fg-primary)]",
  imagePreviewToolbar:
    "vui-components-conversationview imagePreviewToolbar grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-3",
} as const;

export default styles;
