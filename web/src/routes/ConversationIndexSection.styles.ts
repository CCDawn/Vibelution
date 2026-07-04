const styles = {
  conversationGroup:
    "vui-routes-chatcodingroute conversationGroup grid min-w-0 gap-0.5",
  conversationGroupHeader:
    "vui-routes-chatcodingroute conversationGroupHeader !grid !w-full min-h-[28px] grid-cols-[14px_minmax(0,1fr)_auto] items-center gap-1 rounded-none border-0 bg-transparent px-1.5 py-0 text-left text-[var(--vui-font-sm)] font-semibold leading-tight text-[var(--fg-secondary)] shadow-none hover:border-transparent hover:bg-[color-mix(in_srgb,var(--surface-card)_36%,transparent)] [&_[data-slot=vui-button-content]]:contents [&_[data-slot=vui-button-label]]:contents [&_span]:min-w-0 [&_span]:truncate [&_strong]:text-[var(--vui-font-xs)] [&_strong]:font-semibold",
  conversationGroupList:
    "vui-routes-chatcodingroute conversationGroupList grid min-w-0 gap-1",
} as const;

export default styles;
