const panelSurface = "rounded-[var(--radius-panel)] border border-vui-border-subtle bg-[color-mix(in_srgb,var(--vui-surface-panel)_72%,transparent)]";
const rowSurface = "rounded-[var(--radius-control)] border border-vui-border-subtle bg-[color-mix(in_srgb,var(--vui-surface-row)_72%,transparent)]";
const mutedControl =
  "inline-flex min-h-7 w-fit max-w-full flex-none items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-vui-border-soft bg-vui-control-muted px-2 text-[var(--vui-font-xs)] leading-none text-vui-fg-secondary no-underline hover:border-vui-border-soft hover:bg-vui-control-muted-hover hover:text-vui-fg-primary disabled:cursor-default disabled:opacity-55 [&[data-vui]]:min-w-0";
const primaryControl =
  "inline-flex min-h-7 w-fit max-w-full flex-none items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--accent-primary)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-primary)_12%,var(--vui-control-muted))] px-2 text-[var(--vui-font-xs)] leading-none text-vui-fg-primary no-underline hover:border-[color-mix(in_srgb,var(--accent-primary)_44%,transparent)] hover:bg-[color-mix(in_srgb,var(--accent-primary)_18%,var(--vui-control-muted))] disabled:cursor-default disabled:opacity-55 [&[data-vui]]:min-w-0";
const dangerControl =
  "border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[color-mix(in_srgb,var(--danger)_9%,var(--vui-control-muted))] text-[color-mix(in_srgb,var(--danger)_74%,var(--vui-fg-primary))] hover:border-[color-mix(in_srgb,var(--danger)_52%,transparent)] hover:bg-[color-mix(in_srgb,var(--danger)_14%,var(--vui-control-muted))] hover:text-vui-fg-primary";

const styles = {
  cleanupActions: "flex min-w-0 flex-wrap items-center justify-start gap-1.5",
  cleanupConsole: `grid max-h-[220px] min-w-0 gap-1.5 overflow-auto ${rowSurface} p-[7px] [scrollbar-gutter:stable]`,
  cleanupMetrics: "flex min-w-0 flex-wrap items-center gap-1.5 [&_span]:text-[var(--vui-font-xs)] [&_span]:uppercase [&_span]:tracking-[0.06em] [&_span]:text-[var(--fg-tertiary)] [&_strong]:text-[var(--fg-primary)] max-[620px]:grid max-[620px]:grid-cols-[minmax(0,1fr)]",
  cleanupPlan: "grid min-w-0 gap-[3px] rounded-md border border-[color-mix(in_srgb,var(--state-warning)_34%,var(--border-soft))] bg-[color-mix(in_srgb,var(--state-warning)_6%,var(--vui-surface-row))] p-1.5 [&_strong]:min-w-0 [&_strong]:truncate [&_strong]:text-[var(--vui-font-xs)] [&_strong]:text-[var(--fg-primary)] [&_small]:min-w-0 [&_small]:truncate [&_small]:text-[var(--vui-font-xs)] [&_small]:text-[var(--fg-secondary)] [&_li]:min-w-0 [&_li]:truncate [&_li]:text-[var(--vui-font-xs)] [&_li]:text-[var(--fg-secondary)] [&_ul]:m-0 [&_ul]:grid [&_ul]:min-w-0 [&_ul]:gap-0.5 [&_ul]:pl-4",
  compactButton: "inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-[5px] rounded-[var(--radius-control)] border border-vui-border-soft bg-vui-control-muted px-1.5 py-[3px] text-[var(--vui-font-xs)] text-vui-fg-secondary hover:bg-vui-control-muted-hover disabled:cursor-default disabled:opacity-60 [&[data-vui]]:min-w-0",
  dangerButton: dangerControl,
  developerGrid: "grid min-h-0 min-w-0 grid-cols-[minmax(132px,0.36fr)_minmax(0,1fr)_minmax(250px,0.72fr)] gap-1.5 max-[1200px]:grid-cols-[minmax(0,1fr)]",
  developerNoise: `grid min-h-0 min-w-0 gap-1.5 overflow-hidden ${rowSurface} p-[7px]`,
  developerNoiseHeader: "flex min-w-0 items-center justify-between gap-2 [&_span]:text-[var(--vui-font-xs)] [&_span]:uppercase [&_span]:tracking-[0.06em] [&_span]:text-[var(--fg-tertiary)]",
  developerPanel: `mx-2 mt-1.5 grid min-h-0 min-w-0 max-w-full gap-1.5 overflow-hidden ${panelSurface} px-2 py-1.5 data-[enabled=true]:border-[color-mix(in_srgb,var(--state-warning)_42%,transparent)]`,
  developerPanelHeader: "flex min-w-0 items-center justify-between gap-2 max-[860px]:flex-col max-[860px]:items-start [&>div]:grid [&>div]:min-w-0 [&>div]:gap-0.5 [&_strong]:text-[var(--vui-font-xs)] [&_strong]:text-[var(--fg-primary)]",
  developerStatus: `grid min-w-0 content-start gap-1 ${rowSurface} p-[7px] data-[tone=warning]:border-[color-mix(in_srgb,var(--state-warning)_42%,transparent)] [&_span]:text-[var(--vui-font-xs)] [&_span]:uppercase [&_span]:tracking-[0.06em] [&_span]:text-vui-fg-tertiary [&_strong]:min-w-0 [&_strong]:truncate [&_strong]:text-[var(--vui-font-xs)] [&_strong]:text-vui-fg-primary [&_small]:min-w-0 [&_small]:truncate [&_small]:text-[var(--vui-font-xs)] [&_small]:text-vui-fg-secondary`,
  iconButton: mutedControl,
  noiseItem: "grid min-w-0 gap-0.5 rounded-md border border-[color-mix(in_srgb,var(--border-soft)_72%,transparent)] px-1.5 py-[5px] data-[protected=true]:opacity-80 [&_span]:min-w-0 [&_span]:truncate [&_span]:text-[var(--vui-font-xs)] [&_span]:text-[var(--fg-secondary)] [&_strong]:min-w-0 [&_strong]:truncate [&_strong]:text-[var(--vui-font-xs)] [&_strong]:text-[var(--fg-primary)] [&_small]:min-w-0 [&_small]:truncate [&_small]:text-[var(--vui-font-xs)] [&_small]:text-[var(--fg-secondary)]",
  noiseItemGrid: "grid max-h-[150px] min-w-0 grid-cols-4 gap-[5px] overflow-auto pr-0.5 [scrollbar-gutter:stable] max-[860px]:grid-cols-[minmax(0,1fr)]",
  panelEyebrow: "m-0 text-[var(--vui-font-xs)] uppercase tracking-[0.08em] text-[var(--fg-tertiary)]",
  primaryButton: primaryControl,
  settingField: "grid min-w-0 gap-[3px] [&>span]:text-[var(--vui-font-xs)] [&>span]:uppercase [&>span]:tracking-[0.06em] [&>span]:text-[var(--fg-tertiary)] [&>small]:min-w-0 [&>small]:truncate [&>small]:text-[var(--vui-font-xs)] [&>small]:text-[var(--fg-secondary)] [&_input]:min-h-7 [&_input]:w-full [&_input]:min-w-0 [&_input]:rounded-[var(--radius-control)] [&_input]:border [&_input]:border-[var(--border-soft)] [&_input]:bg-[var(--vui-surface-row)] [&_input]:px-[7px] [&_input]:py-[3px] [&_input]:text-[var(--vui-font-xs)] [&_input]:text-[var(--fg-primary)] [&_select]:min-h-7 [&_select]:w-full [&_select]:min-w-0 [&_select]:rounded-[var(--radius-control)] [&_select]:border [&_select]:border-[var(--border-soft)] [&_select]:bg-[var(--vui-surface-row)] [&_select]:px-[7px] [&_select]:py-[3px] [&_select]:text-[var(--vui-font-xs)] [&_select]:text-[var(--fg-primary)]",
  spin: "animate-spin",
} as const;

export default styles;
