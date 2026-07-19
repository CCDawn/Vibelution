const routeClass = "grid h-full min-h-0 min-w-0 max-w-full grid-rows-[auto_minmax(0,1fr)] overflow-x-hidden";
const panelSurface = "rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--vui-border-subtle)_72%,transparent)] bg-[color-mix(in_srgb,var(--vui-surface-panel)_62%,transparent)]";
const headerClass = "mx-2 mt-1.5 min-w-0 border-[color-mix(in_srgb,var(--vui-border-subtle)_78%,transparent)] bg-[var(--vui-gradient-route-soft),color-mix(in_srgb,var(--vui-surface-panel)_70%,transparent)]";
const headerActionsClass = "flex flex-wrap items-center justify-end gap-2";
const secondaryButtonClass = "inline-flex w-fit max-w-full min-h-8 items-center justify-center gap-[7px] rounded-[var(--radius-control)] border border-vui-border-soft bg-[color-mix(in_srgb,var(--vui-control-muted)_72%,transparent)] px-2.5 py-1.5 text-[var(--vui-font-xs)] text-vui-fg-secondary hover:border-[var(--border-strong)] hover:bg-[var(--vui-control-muted-hover)] hover:text-vui-fg-primary";
const workspaceClass = "grid min-h-0 min-w-0 max-w-full grid-cols-[minmax(0,1.2fr)_clamp(260px,28vw,420px)] items-start justify-start gap-2 overflow-y-auto overflow-x-hidden px-2 pb-2 pt-1.5 max-[760px]:grid-cols-[minmax(0,1fr)]";
const primaryColumnClass = "grid min-w-0 max-w-none content-start gap-2";
const statusStripClass = `grid min-w-0 max-w-none grid-cols-[auto_minmax(0,1fr)] items-start gap-2 overflow-hidden ${panelSurface} p-2`;
const launcherPanelClass = `grid min-w-0 max-w-none content-start gap-2 ${panelSurface} p-2.5`;
const riskPanelClass = `grid min-w-0 max-w-none content-start gap-2 ${panelSurface} p-2.5`;
const cardClass = `min-h-0 min-w-0 ${panelSurface} p-2`;
const cardTitleRowClass = "flex min-w-0 items-center gap-1.5 text-vui-fg-primary [&_svg]:shrink-0";
const cardTitleClass = "m-0 text-[0.94rem] font-bold";
const statusIconClass = "grid h-7 w-7 shrink-0 place-items-center rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--state-success)_34%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]";
const statusLabelClass = "m-0 text-[var(--vui-font-xs)] font-semibold uppercase tracking-[0.08em] text-[var(--state-success)]";
const copyStackClass = "grid min-w-0 gap-0.5";
const copyTextClass = "m-0 min-w-0 break-words [overflow-wrap:anywhere] text-[var(--route-topbar-subtitle-size)] leading-[1.35] text-vui-fg-secondary";
const actionRowClass = "flex min-w-0 flex-wrap items-center gap-2 pt-0.5";
const actionMetaClass = "min-w-0 break-words [overflow-wrap:anywhere] text-[var(--vui-font-xs)] text-vui-fg-tertiary";
const riskListClass = "grid max-h-[220px] min-w-0 content-start gap-1.5 overflow-auto [scrollbar-gutter:stable]";
const riskItemClass = "grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-start gap-1.5 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--vui-border-subtle)_62%,transparent)] bg-[color-mix(in_srgb,var(--vui-surface-row)_58%,transparent)] px-2 py-1.5 text-vui-fg-secondary [&_svg]:mt-0.5 [&_svg]:shrink-0 [&_svg]:text-[var(--state-success)] [&_strong]:min-w-0 [&_strong]:break-words [&_strong]:[overflow-wrap:anywhere] [&_strong]:text-[var(--vui-font-xs)] [&_strong]:text-vui-fg-primary [&_small]:min-w-0 [&_small]:break-words [&_small]:[overflow-wrap:anywhere] [&_small]:text-[var(--vui-font-xs)] [&_small]:leading-[1.3] [&_small]:text-vui-fg-secondary";
const subtitleClass = "m-0 min-w-0 break-words [overflow-wrap:anywhere] text-[var(--route-topbar-subtitle-size)] leading-[1.25] text-vui-fg-secondary";

const styles = {
  routeClass,
  headerClass,
  headerActionsClass,
  secondaryButtonClass,
  workspaceClass,
  primaryColumnClass,
  statusStripClass,
  launcherPanelClass,
  riskPanelClass,
  cardClass,
  cardTitleRowClass,
  cardTitleClass,
  statusIconClass,
  statusLabelClass,
  copyStackClass,
  copyTextClass,
  actionRowClass,
  actionMetaClass,
  riskListClass,
  riskItemClass,
  subtitleClass,
} as const;

export default styles;
