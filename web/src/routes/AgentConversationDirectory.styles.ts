const styles = {
  agentDirectory:
    "vui-routes-agentconversationdirectory grid min-w-0 gap-1.5 border-b border-[var(--vui-border-subtle)] pb-2",
  agentDirectoryHeader:
    "vui-routes-agentconversationdirectory agentDirectoryHeader flex min-w-0 items-center justify-between px-2.5 pt-1 text-[var(--vui-font-xs)] font-semibold uppercase tracking-[0.08em] text-[var(--fg-tertiary)]",
  agentDirectoryCount:
    "vui-routes-agentconversationdirectory agentDirectoryCount tabular-nums text-[var(--fg-secondary)]",
  agentDirectoryList:
    "vui-routes-agentconversationdirectory agentDirectoryList grid min-w-0 gap-px",
  agentRow:
    "vui-routes-agentconversationdirectory agentRow grid min-w-0 grid-cols-[32px_minmax(0,1fr)] items-center gap-2.5 rounded-[var(--radius-control)] border border-transparent px-2.5 py-2 text-left transition-[background-color,border-color,box-shadow] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)]",
  agentRowActive:
    "vui-routes-agentconversationdirectory agentRowActive border-[color-mix(in_srgb,var(--accent-cool)_44%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_9%,var(--vui-surface-row))] shadow-[var(--vui-shadow-inset-accent)]",
  agentAvatar:
    "vui-routes-agentconversationdirectory agentAvatar grid h-8 w-8 place-items-center overflow-hidden rounded-full border border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_9%,transparent)] text-[var(--vui-font-xs)] font-semibold text-[var(--accent-cool)]",
  agentAvatarImage:
    "vui-routes-agentconversationdirectory agentAvatarImage h-full w-full object-cover",
  agentCopy:
    "vui-routes-agentconversationdirectory agentCopy grid min-w-0 gap-0.5",
  agentTitleRow:
    "vui-routes-agentconversationdirectory agentTitleRow flex min-w-0 items-center gap-1.5",
  agentTitle:
    "vui-routes-agentconversationdirectory agentTitle min-w-0 flex-1 truncate text-[var(--vui-font-md)] font-semibold leading-tight text-[var(--fg-primary)]",
  agentStatus:
    "vui-routes-agentconversationdirectory agentStatus h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--fg-tertiary)]",
  agentStatusRunning:
    "vui-routes-agentconversationdirectory agentStatusRunning bg-[var(--state-success)] shadow-[0_0_0_2px_color-mix(in_srgb,var(--state-success)_14%,transparent)]",
  agentStatusError:
    "vui-routes-agentconversationdirectory agentStatusError bg-[var(--state-error)]",
  agentMeta:
    "vui-routes-agentconversationdirectory agentMeta flex min-w-0 items-center gap-1.5 truncate text-[var(--vui-font-xs)] leading-tight text-[var(--fg-secondary)]",
  agentMetaItem:
    "vui-routes-agentconversationdirectory agentMetaItem min-w-0 truncate",
  agentMetaCount:
    "vui-routes-agentconversationdirectory agentMetaCount shrink-0 text-[var(--fg-tertiary)]",
  agentEmpty:
    "vui-routes-agentconversationdirectory agentEmpty rounded-[var(--radius-control)] border border-dashed border-[var(--vui-border-subtle)] px-2.5 py-3 text-[var(--vui-font-sm)] text-[var(--fg-secondary)]",
} as const;

export default styles;
