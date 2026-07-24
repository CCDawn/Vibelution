// Always lives in the narrow team inspector rail (≈320–420px). Prefer stacked
// identity cards over a rigid 4-column table that overflows and clips actions.
const compactActionLink =
  "[&_a]:inline-flex [&_a]:w-fit [&_a]:flex-none [&_a]:min-h-7 [&_a]:max-w-full [&_a]:items-center [&_a]:justify-center [&_a]:gap-1 [&_a]:rounded-[var(--radius-control)] [&_a]:border [&_a]:border-[color:color-mix(in_srgb,var(--accent-cool)_30%,var(--vui-border-subtle))] [&_a]:bg-[color:color-mix(in_srgb,var(--vui-surface-panel)_88%,transparent)] [&_a]:px-2 [&_a]:text-[var(--fg-primary)] [&_a]:[font-size:var(--vui-font-xs)] [&_a]:font-[760] [&_a]:no-underline [&_a]:whitespace-nowrap [&_a:hover]:border-[color:color-mix(in_srgb,var(--accent-cool)_46%,var(--vui-border-subtle))] [&_a:hover]:bg-[color:color-mix(in_srgb,var(--accent-cool)_8%,var(--vui-surface-panel))]";

const styles = {
  empty:
    "empty min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  teamMemoryActionRail:
    `teamMemoryActionRail min-w-0 flex flex-wrap items-center justify-end gap-1.5 ${compactActionLink}`,
  teamMemoryIndex:
    "teamMemoryIndex min-w-0 !flex-none grid gap-2.5 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-2.5",
  teamMemoryIndexHeader:
    "teamMemoryIndexHeader min-w-0 flex flex-wrap items-start justify-between gap-2 [&>div]:grid [&>div]:min-w-0 [&>div]:gap-0.5 [&>div_strong]:truncate [&>div_strong]:text-[var(--fg-primary)] [&>div_span]:truncate [&>div_span]:text-[var(--fg-muted)] [&>div_span]:[font-size:var(--vui-font-xs)] [&>div_span]:font-[760]",
  teamMemoryMemberActions:
    `teamMemoryMemberActions min-w-0 flex flex-none flex-wrap items-center justify-end gap-1 self-start ${compactActionLink}`,
  teamMemoryMemberCard:
    "teamMemoryMemberCard min-w-0 grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-2 gap-y-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] px-2.5 py-2",
  teamMemoryMemberHeading:
    "teamMemoryMemberHeading sr-only",
  teamMemoryMemberIdentity:
    "teamMemoryMemberIdentity min-w-0 grid gap-0.5 [&_strong]:min-w-0 [&_strong]:truncate [&_strong]:text-[var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-sm)] [&_strong]:font-[760] [&_span]:min-w-0 [&_span]:truncate [&_span]:text-[var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)]",
  teamMemoryMemberMain:
    "teamMemoryMemberMain min-w-0 grid gap-1 content-start",
  teamMemoryMemberMeta:
    "teamMemoryMemberMeta min-w-0 flex flex-wrap items-center gap-1.5",
  teamMemoryMemberTable:
    "teamMemoryMemberTable min-w-0 !grid grid-cols-[minmax(0,1fr)] content-start auto-rows-max gap-1.5",
  teamMemoryRole:
    "teamMemoryRole min-w-0 block max-w-full truncate font-mono [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)]",
  teamMemoryStatusBadge:
    "teamMemoryStatusBadge min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 [font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
} as const;

export default styles;
