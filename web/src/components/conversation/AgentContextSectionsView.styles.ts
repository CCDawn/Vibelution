const styles = {
  composerReferenceChip:
    "vui-components-conversationview composerReferenceChip min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  composerReferenceCopy:
    "vui-components-conversationview composerReferenceCopy min-w-0 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  composerReferenceIcon:
    "vui-components-conversationview composerReferenceIcon min-w-0 shrink-0 text-[var(--fg-tertiary)]",
  imageDownloadButton:
    "vui-components-conversationview imageDownloadButton min-w-0 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 text-[var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--border-strong)] hover:bg-[var(--vui-control-muted-hover)] hover:text-[var(--fg-primary)] disabled:cursor-default disabled:opacity-55",
  userAttachment:
    "vui-components-conversationview userAttachment min-w-0",
  userAttachmentGrid:
    "vui-components-conversationview userAttachmentGrid min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  userAttachmentImage:
    "vui-components-conversationview userAttachmentImage min-w-0",
  userAttachmentMeta:
    "vui-components-conversationview userAttachmentMeta min-w-0 flex flex-wrap items-center gap-1.5",
  userContextReferences:
    "vui-components-conversationview userContextReferences min-w-0 flex flex-wrap justify-end gap-1.5",
  userContextSection:
    "vui-components-conversationview userContextSection min-w-0 grid gap-2",
} as const;

export default styles;
