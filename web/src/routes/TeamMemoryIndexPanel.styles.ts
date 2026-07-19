const styles = {
  empty:
    "empty min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  teamMemoryActionRail:
    "teamMemoryActionRail min-w-0 flex flex-wrap items-center justify-end gap-1.5 [&_a]:inline-flex [&_a]:w-fit [&_a]:max-w-full [&_a]:min-h-8 [&_a]:items-center [&_a]:justify-center [&_a]:gap-1.5 [&_a]:px-2.5 [&_a]:rounded-[var(--radius-control)] [&_a]:border [&_a]:border-[color:color-mix(in_srgb,var(--accent-cool)_30%,var(--vui-border-subtle))] [&_a]:bg-[color:color-mix(in_srgb,var(--vui-surface-panel)_88%,transparent)] [&_a]:text-[var(--fg-primary)] [&_a]:font-[820] [&_a]:no-underline [&_a]:whitespace-nowrap [&_a:hover]:border-[color:color-mix(in_srgb,var(--accent-cool)_46%,var(--vui-border-subtle))] [&_a:hover]:bg-[color:color-mix(in_srgb,var(--accent-cool)_8%,var(--vui-surface-panel))]",
  teamMemoryIndex:
    "teamMemoryIndex min-w-0 !flex-none grid gap-3 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-3",
  teamMemoryIndexHeader:
    "teamMemoryIndexHeader min-w-0 flex flex-wrap items-center gap-1.5 !flex min-w-0 items-center justify-between gap-2 [&>div]:grid [&>div]:min-w-0 [&>div]:gap-0.5 [&>div_strong]:truncate [&>div_strong]:text-[var(--fg-primary)] [&>div_span]:truncate [&>div_span]:text-[var(--fg-muted)] [&>div_span]:font-[760]",
  teamMemoryMemberActions:
    "teamMemoryMemberActions min-w-0 flex flex-wrap items-center justify-end gap-1.5 [&_a]:inline-flex [&_a]:flex-none [&_a]:min-h-8 [&_a]:items-center [&_a]:justify-center [&_a]:gap-1.5 [&_a]:rounded-[var(--radius-control)] [&_a]:border [&_a]:border-[color:color-mix(in_srgb,var(--accent-cool)_30%,var(--vui-border-subtle))] [&_a]:bg-[color:color-mix(in_srgb,var(--vui-surface-panel)_88%,transparent)] [&_a]:px-2 [&_a]:text-[var(--fg-primary)] [&_a]:font-[760] [&_a]:no-underline",
  teamMemoryMemberCard:
    "teamMemoryMemberCard min-w-0 grid grid-cols-[minmax(10rem,1.1fr)_minmax(11rem,1.4fr)_max-content_auto] items-center gap-3 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] px-3 py-2 max-[720px]:grid-cols-[minmax(0,1fr)_auto] max-[720px]:gap-2",
  teamMemoryMemberHeading:
    "teamMemoryMemberHeading min-w-0 grid grid-cols-[minmax(10rem,1.1fr)_minmax(11rem,1.4fr)_max-content_auto] gap-3 px-3 [font-size:var(--vui-font-xs)] font-[760] text-[var(--fg-muted)] max-[720px]:hidden",
  teamMemoryMemberIdentity:
    "teamMemoryMemberIdentity min-w-0 grid gap-1",
  teamMemoryMemberTable:
    "teamMemoryMemberTable min-w-0 !grid grid-cols-[minmax(0,1fr)] content-start auto-rows-max gap-1.5",
  teamMemoryRole:
    "teamMemoryRole min-w-0 block max-w-full truncate font-mono [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)]",
  teamMemoryStatusBadge:
    "teamMemoryStatusBadge min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 [font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
} as const;

export default styles;
