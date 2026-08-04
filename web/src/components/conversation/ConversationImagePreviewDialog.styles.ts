import {
  vuiFlatPanelClass,
  vuiGlassPanelClass,
} from "../../design/vuiSurfaceRecipes";

const styles = {
  imageDownloadButton:
    "vui-components-conversationview imageDownloadButton inline-flex h-8 shrink-0 items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2.5 [font-size:var(--vui-font-xs)] font-semibold text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-cool)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--vui-surface-panel)]",
  // Wave 6H: viewport clamp on VDialog content — not workbench pane-heights.
  imagePreviewDialog: `vui-components-conversationview imagePreviewDialog w-[min(100vw-2rem,72rem)] max-h-[calc(100dvh-2rem)] ${vuiFlatPanelClass}`,
  imagePreviewLarge: `vui-components-conversationview imagePreviewLarge block max-h-[calc(100dvh-10rem)] max-w-full min-w-0 justify-self-center ${vuiGlassPanelClass} object-contain shadow-[var(--vui-shadow-hairline)]`,
} as const;

export default styles;
