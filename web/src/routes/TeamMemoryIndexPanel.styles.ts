const styles = {
  empty:
    "empty min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  teamMemoryActionRail:
    "teamMemoryActionRail min-w-0 flex flex-wrap items-center justify-end gap-[5px] [&_a]:inline-flex [&_a]:w-fit [&_a]:max-w-full [&_a]:min-h-[24px] [&_a]:items-center [&_a]:justify-center [&_a]:gap-1 [&_a]:px-[7px] [&_a]:rounded-[var(--radius-control)] [&_a]:border [&_a]:border-[color:color-mix(in_srgb,var(--accent-cool)_30%,var(--vui-border-subtle))] [&_a]:bg-[color:color-mix(in_srgb,var(--vui-surface-panel)_88%,transparent)] [&_a]:text-[var(--fg-primary)] [&_a]:font-[820] [&_a]:no-underline [&_a]:whitespace-nowrap [&_a:hover]:border-[color:color-mix(in_srgb,var(--accent-cool)_46%,var(--vui-border-subtle))] [&_a:hover]:bg-[color:color-mix(in_srgb,var(--accent-cool)_8%,var(--vui-surface-panel))]",
  teamMemoryIndex:
    "teamMemoryIndex min-w-0 !flex-none min-h-0 grid max-h-[36vh] gap-2 grid-rows-[auto_minmax(0,1fr)] grid-cols-[minmax(0,1fr)] overflow-hidden rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-2",
  teamMemoryIndexHeader:
    "teamMemoryIndexHeader min-w-0 flex flex-wrap items-center gap-1.5 !flex min-w-0 items-center justify-between gap-2 [&>div]:grid [&>div]:min-w-0 [&>div]:gap-0.5 [&>div_strong]:truncate [&>div_strong]:text-[var(--fg-primary)] [&>div_span]:truncate [&>div_span]:text-[var(--fg-muted)] [&>div_span]:font-[760]",
  teamMemoryMemberActions:
    "teamMemoryMemberActions min-w-0 flex flex-wrap items-center justify-end gap-[5px] [&_a_span]:hidden [&_a]:inline-flex [&_a]:flex-none [&_a]:items-center [&_a]:justify-center [&_a]:w-[26px] [&_a]:min-w-[26px] [&_a]:min-h-[24px] [&_a]:rounded-[var(--radius-control)] [&_a]:border [&_a]:border-[color:color-mix(in_srgb,var(--accent-cool)_30%,var(--vui-border-subtle))] [&_a]:bg-[color:color-mix(in_srgb,var(--vui-surface-panel)_88%,transparent)] [&_a]:text-[var(--fg-primary)] [&_a]:no-underline",
  teamMemoryMemberCard:
    "teamMemoryMemberCard min-w-0 grid grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_max-content_auto] items-center gap-2 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] px-2 py-1.5 max-[720px]:grid-cols-[minmax(0,1fr)_auto]",
  teamMemoryMemberHeading:
    "teamMemoryMemberHeading min-w-0 hidden",
  teamMemoryMemberIdentity:
    "teamMemoryMemberIdentity min-w-0 grid gap-1",
  teamMemoryMemberTable:
    "teamMemoryMemberTable min-w-0 min-h-0 !grid grid-cols-[minmax(0,1fr)] content-start auto-rows-max gap-1.5 overflow-auto pr-1 [scrollbar-gutter:stable]",
  teamMemoryRole:
    "teamMemoryRole min-w-0 block max-w-full truncate font-mono text-[var(--vui-font-xs)] text-[var(--fg-secondary)]",
  teamMemoryStatusBadge:
    "teamMemoryStatusBadge min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
} as const;

export default styles;
