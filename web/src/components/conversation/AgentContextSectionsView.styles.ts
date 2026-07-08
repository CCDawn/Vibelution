const styles = {
  composerReferenceChip:
    "vui-components-conversationview composerReferenceChip min-w-0 inline-flex min-h-6 w-fit max-w-[min(100%,32rem)] items-start justify-start gap-1.5 overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1.5 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  composerReferenceCopy:
    "vui-components-conversationview composerReferenceCopy grid min-w-0 gap-0.5 text-left",
  composerReferenceIcon:
    "vui-components-conversationview composerReferenceIcon min-w-0 shrink-0 pt-0.5 text-[var(--fg-tertiary)]",
  composerReferenceMeta:
    "vui-components-conversationview composerReferenceMeta min-w-0 truncate text-[var(--vui-font-xs)] font-medium leading-tight text-[var(--fg-tertiary)]",
  composerReferenceTitle:
    "vui-components-conversationview composerReferenceTitle min-w-0 truncate text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] [overflow-wrap:anywhere]",
  imageDownloadButton:
    "vui-components-conversationview imageDownloadButton min-w-0 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 text-[var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55",
  userAttachment:
    "vui-components-conversationview userAttachment min-w-0 overflow-hidden rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)]",
  userAttachmentGrid:
    "vui-components-conversationview userAttachmentGrid min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(min(12rem,100%),1fr))]",
  userAttachmentImage:
    "vui-components-conversationview userAttachmentImage block aspect-[16/9] max-h-44 w-full min-w-0 object-cover",
  userAttachmentMeta:
    "vui-components-conversationview userAttachmentMeta grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-1.5 px-2 py-1.5 [&>span]:truncate",
  userContextReferences:
    "vui-components-conversationview userContextReferences min-w-0 flex flex-wrap justify-end gap-1.5",
  userContextSection:
    "vui-components-conversationview userContextSection min-w-0 grid gap-2",
} as const;

export default styles;
