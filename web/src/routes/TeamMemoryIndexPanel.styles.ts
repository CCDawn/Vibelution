const styles = {
  empty:
    "empty min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  teamMemoryActionRail:
    "teamMemoryActionRail min-w-0 flex flex-wrap items-center gap-1.5 grid min-h-0 content-start overflow-auto !flex min-w-0 items-center justify-end gap-[5px] [&_a]:inline-flex [&_a]:min-h-[24px] [&_a]:items-center [&_a]:justify-center [&_a]:gap-1 [&_a]:px-[7px] [&_a]:rounded-[7px] [&_a]:border [&_a]:border-[color:color-mix(in_srgb,var(--accent-cool)_30%,var(--border-soft))] [&_a]:bg-[color:color-mix(in_srgb,var(--surface-panel)_88%,transparent)] [&_a]:text-[var(--fg-primary)] [&_a]:font-[820] [&_a]:no-underline [&_a]:whitespace-nowrap [&_a:hover]:border-[color:color-mix(in_srgb,var(--accent-cool)_46%,var(--border-soft))] [&_a:hover]:bg-[color:color-mix(in_srgb,var(--accent-cool)_8%,var(--surface-panel))]",
  teamMemoryIndex:
    "teamMemoryIndex min-w-0 !flex-1 min-h-0 grid gap-2 grid-rows-[auto_minmax(0,1fr)] grid-cols-[minmax(0,1fr)]",
  teamMemoryIndexHeader:
    "teamMemoryIndexHeader min-w-0 flex flex-wrap items-center gap-1.5 !flex min-w-0 items-center justify-between gap-2 [&>div]:grid [&>div]:min-w-0 [&>div]:gap-0.5 [&>div_strong]:truncate [&>div_strong]:text-[var(--fg-primary)] [&>div_span]:truncate [&>div_span]:text-[var(--fg-muted)] [&>div_span]:font-[760]",
  teamMemoryMemberActions:
    "teamMemoryMemberActions min-w-0 flex flex-wrap items-center gap-1.5 !flex items-center justify-end gap-[5px] min-w-0 [&_a_span]:hidden [&_a]:inline-flex [&_a]:items-center [&_a]:justify-center [&_a]:w-[26px] [&_a]:min-w-[26px] [&_a]:min-h-[24px] [&_a]:rounded-[7px] [&_a]:border [&_a]:border-[color:color-mix(in_srgb,var(--accent-cool)_30%,var(--border-soft))] [&_a]:bg-[color:color-mix(in_srgb,var(--surface-panel)_88%,transparent)] [&_a]:text-[var(--fg-primary)] [&_a]:no-underline",
  teamMemoryMemberCard:
    "teamMemoryMemberCard min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  teamMemoryMemberHeading:
    "teamMemoryMemberHeading min-w-0 hidden",
  teamMemoryMemberIdentity:
    "teamMemoryMemberIdentity min-w-0 grid gap-1",
  teamMemoryMemberTable:
    "teamMemoryMemberTable min-w-0 min-h-0 !grid grid-cols-[repeat(auto-fit,minmax(260px,max-content))] justify-start content-start auto-rows-max gap-2 overflow-auto",
  teamMemoryRole:
    "teamMemoryRole min-w-0",
  teamMemoryStatusBadge:
    "teamMemoryStatusBadge min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
} as const;

export default styles;
