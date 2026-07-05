const styles = {
  conversationGroup:
    "vui-routes-chatcodingroute conversationGroup grid min-w-0 gap-0.5",
  conversationGroupHeader:
    "vui-routes-chatcodingroute conversationGroupHeader !grid !w-full min-h-[28px] grid-cols-[14px_minmax(0,1fr)_auto] items-center gap-1 rounded-[var(--radius-control)] border-0 bg-transparent px-1.5 py-0 text-left text-[var(--vui-font-sm)] font-semibold leading-tight text-[var(--fg-secondary)] shadow-none transition-colors hover:border-transparent hover:bg-[color-mix(in_srgb,var(--surface-card)_38%,transparent)] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_36%,transparent)] [&_svg]:transition-transform [&[aria-expanded=true]_svg]:rotate-90 [&_span]:min-w-0 [&_span]:truncate [&_strong]:inline-grid [&_strong]:min-w-5 [&_strong]:place-items-center [&_strong]:rounded-full [&_strong]:bg-[color-mix(in_srgb,var(--vui-control-muted)_78%,transparent)] [&_strong]:px-1.5 [&_strong]:text-[var(--vui-font-xs)] [&_strong]:font-semibold [&_strong]:text-[var(--fg-secondary)]",
  conversationGroupList:
    "vui-routes-chatcodingroute conversationGroupList grid min-w-0 gap-1",
} as const;

export default styles;
