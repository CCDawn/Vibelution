import {
  vuiGlassPanelClass,
} from "../../design/vuiSurfaceRecipes";

const styles = {
  imageArtifact:
    "vui-components-conversationview imageArtifact grid min-w-0 gap-2",
  imageArtifactFooter:
    "vui-components-conversationview imageArtifactFooter grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2",
  imageArtifactFrame: `vui-components-conversationview imageArtifactFrame block aspect-square w-[min(100%,18rem)] min-w-0 overflow-hidden ${vuiGlassPanelClass}`,
  imageArtifactMeta:
    "vui-components-conversationview imageArtifactMeta grid min-w-0 gap-0.5 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  imageArtifactPrompt:
    "vui-components-conversationview imageArtifactPrompt min-w-0 truncate [font-size:var(--vui-font-sm)] font-medium leading-[var(--vui-line-compact)] text-[var(--fg-secondary)]",
  imageDownloadButton:
    "vui-components-conversationview imageDownloadButton inline-flex size-[var(--vui-control-height-sm)] shrink-0 items-center justify-center rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-cool)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--vui-surface-panel)]",
  imagePreview:
    "vui-components-conversationview imagePreview size-full min-w-0 object-cover",
  imagePreviewButton:
    "vui-components-conversationview imagePreviewButton inline-flex w-fit min-w-0 rounded-[var(--radius-panel)] p-0 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-cool)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--vui-surface-panel)]",
} as const;

export default styles;
