const styles = {
  conversationFrame:
    "vui-routes-chatsessionworkspacepanel conversationFrame relative flex h-full min-h-0 min-w-0 flex-col overflow-hidden",
  conversationFrameFocus:
    "vui-routes-chatsessionworkspacepanel conversationFrameFocus min-w-0 justify-self-center w-[min(calc(100%_-_48px),1480px)] max-w-full max-[980px]:w-full",
  emptyConversationSurface:
    "vui-routes-chatsessionworkspacepanel emptyConversationSurface min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)] grid min-h-[74px] w-[min(360px,calc(100%_-_32px))] place-self-center place-items-center rounded-[var(--radius-panel)] border border-dashed border-[var(--vui-border-subtle)] bg-[color-mix(in_srgb,var(--vui-surface-row)_58%,transparent)] px-4 py-3 text-center text-[var(--vui-font-sm)] font-semibold leading-tight text-[var(--fg-secondary)] shadow-[var(--vui-shadow-hairline)]",
  emptySurface:
    "vui-routes-chatsessionworkspacepanel emptySurface min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)] grid h-full min-h-[min(420px,calc(100dvh_-_190px))] place-items-center px-4 py-8 text-center text-[var(--fg-secondary)]",
  inlineNotice:
    "vui-routes-chatsessionworkspacepanel inlineNotice min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  loadingSurface:
    "vui-routes-chatsessionworkspacepanel loadingSurface min-w-0 grid min-h-[120px] content-start gap-2 rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--vui-border-subtle)_72%,transparent)] bg-[color-mix(in_srgb,var(--vui-surface-panel)_62%,transparent)] p-3 text-left text-[var(--vui-font-xs)] leading-tight text-[var(--fg-secondary)]",
  loadingSurfaceBody:
    "vui-routes-chatsessionworkspacepanel loadingSurfaceBody grid max-w-[560px] min-w-0 content-start gap-2 [&_strong]:text-[var(--fg-primary)]",
  loadingSkeletonLine:
    "vui-routes-chatsessionworkspacepanel loadingSkeletonLine block h-2 w-[min(100%,520px)] animate-pulse rounded-full bg-[var(--vui-gradient-route-soft)]",
  loadingSkeletonLineShort:
    "vui-routes-chatsessionworkspacepanel loadingSkeletonLineShort block h-2 w-[min(58%,320px)] animate-pulse rounded-full bg-[var(--vui-gradient-route-soft)]",
} as const;

export default styles;
