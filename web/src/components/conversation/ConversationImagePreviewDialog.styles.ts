import {
  vuiFlatPanelClass,
  vuiGlassPanelClass,
} from "../../design/vuiSurfaceRecipes";

const styles = {
  imageDownloadButton:
    "vui-components-conversationview imageDownloadButton inline-flex h-8 shrink-0 items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2.5 text-vui-xs font-semibold text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-cool)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--vui-surface-panel)]",
  // Wave 6H: viewport clamp on VDialog content — not workbench pane-heights.
  imagePreviewDialog: `vui-components-conversationview imagePreviewDialog w-[min(100vw-2rem,72rem)] max-h-[calc(100dvh-2rem)] ${vuiFlatPanelClass}`,
  imagePreviewLarge: `vui-components-conversationview imagePreviewLarge block max-h-[calc(100dvh-10rem)] max-w-full min-w-0 justify-self-center origin-center select-none object-contain shadow-[var(--vui-shadow-hairline)] transition-transform duration-150 ease-out motion-reduce:transition-none ${vuiGlassPanelClass}`,
  // Pan/pinch frames bypass the easing so the image tracks the pointer 1:1;
  // reduced-motion keeps transitions off in both variants.
  imagePreviewLargePanning: `vui-components-conversationview imagePreviewLargePanning block max-h-[calc(100dvh-10rem)] max-w-full min-w-0 justify-self-center origin-center select-none object-contain shadow-[var(--vui-shadow-hairline)] transition-none motion-reduce:transition-none ${vuiGlassPanelClass}`,
  imagePreviewViewport:
    "vui-components-conversationview imagePreviewViewport flex min-h-0 w-full cursor-grab touch-none select-none items-center justify-center overflow-hidden rounded-[var(--radius-panel)] outline-none active:cursor-grabbing",
  imagePreviewViewportGrabbing:
    "vui-components-conversationview imagePreviewViewportGrabbing cursor-grabbing active:cursor-grabbing",
  zoomToolbar:
    "vui-components-conversationview zoomToolbar flex items-center gap-1 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] p-1",
  zoomControlButton:
    "vui-components-conversationview zoomControlButton inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-[var(--radius-control)] border border-transparent text-[var(--fg-secondary)] hover:border-[var(--vui-border-subtle)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:pointer-events-none disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-cool)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--vui-surface-panel)]",
  zoomLevelLabel:
    "vui-components-conversationview zoomLevelLabel min-w-[3rem] text-center text-vui-xs font-semibold tabular-nums text-[var(--fg-primary)]",
  imagePreviewFooter:
    "vui-components-conversationview imagePreviewFooter flex min-w-0 flex-1 flex-wrap items-center justify-between gap-2",
} as const;

export default styles;
