const styles = {
  turnAvatar:
    "vui-components-conversationview turnAvatar mt-0.5 grid size-8 shrink-0 place-items-center overflow-hidden rounded-full bg-[var(--vui-control-muted)] text-[var(--fg-tertiary)]",
  turnContent:
    "vui-components-conversationview turnContent grid min-w-0 gap-[5px]",
  turnMeta:
    "vui-components-conversationview turnMeta inline-flex min-w-0 items-center justify-start gap-2 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  turnMetaActions:
    "vui-components-conversationview turnMetaActions inline-flex min-w-0 items-center justify-start gap-2 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  turnMetaIdentity:
    "vui-components-conversationview turnMetaIdentity flex min-w-0 items-center gap-2",
  turnSpeaker:
    "vui-components-conversationview turnSpeaker min-w-0 truncate text-[var(--vui-font-md)] font-semibold leading-tight text-[var(--fg-primary)]",
} as const;

export default styles;
