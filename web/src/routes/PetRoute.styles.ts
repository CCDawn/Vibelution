const pageClass = "grid h-full min-h-0 content-start gap-1.5 overflow-auto p-[var(--route-workspace-padding)]";
const surfaceClass = "rounded-lg border border-vui-border-soft bg-[var(--surface-panel)]";
const heroClass = `${surfaceClass} grid grid-cols-[auto_minmax(0,1fr)] items-center gap-2.5 p-[var(--route-topbar-padding)] max-[640px]:grid-cols-1`;
const avatarPanelClass = "inline-flex min-w-0 items-center gap-[7px] rounded-lg bg-[var(--surface-panel-strong)] px-2 py-1.5";
const avatarOrbClass = "grid h-[34px] w-[34px] place-items-center rounded-lg bg-[color-mix(in_srgb,var(--accent-warm)_18%,transparent)] font-[var(--font-body)] text-base font-bold text-[var(--accent-warm-2)]";
const avatarMetaClass = "m-0 max-w-[110px] truncate text-[var(--vui-font-xs)] text-vui-fg-secondary";
const heroCopyClass = "min-w-0";
const eyebrowClass = "m-0 mb-[3px] text-[var(--vui-font-xs)] uppercase tracking-[0.08em] text-vui-fg-tertiary";
const titleClass = "m-0 text-[var(--route-topbar-title-size)] font-bold leading-[1.1] text-vui-fg-primary";
const statusLineClass = "m-0 mt-0.5 truncate text-[var(--route-topbar-subtitle-size)] text-vui-fg-secondary max-[640px]:whitespace-normal";
const metricGridClass = "grid grid-cols-4 gap-1.5 max-[860px]:grid-cols-2 max-[640px]:grid-cols-1";
const metricCardClass = `${surfaceClass} grid grid-cols-[auto_minmax(0,1fr)] items-baseline gap-2 p-[9px]`;
const metricLabelClass = "whitespace-nowrap text-[var(--vui-font-xs)] text-vui-fg-secondary";
const metricValueClass = "min-w-0 truncate text-[0.9rem] text-vui-fg-primary";
const statusGridClass = "grid grid-cols-3 items-start gap-1.5 max-[860px]:grid-cols-2 max-[640px]:grid-cols-1";
const cardClass = `${surfaceClass} p-[9px]`;
const cardTitleClass = eyebrowClass;
const statListClass = "grid gap-1 text-[var(--vui-font-xs)] text-vui-fg-secondary";
const progressTrackClass = "h-1.5 overflow-hidden rounded-[var(--radius-control)] bg-[var(--surface-panel-strong)]";
const progressFillClass = "h-full bg-[var(--vui-gradient-route-soft)]";
const supportTextClass = "text-vui-fg-secondary";
const badgeRowClass = "flex flex-wrap gap-1.5";
const badgeClass = "rounded-[var(--radius-control)] bg-[color-mix(in_srgb,var(--accent-cool)_12%,transparent)] px-[7px] py-1 text-[var(--vui-font-xs)] text-[var(--accent-cool)]";

const styles = {
  pageClass,
  surfaceClass,
  heroClass,
  avatarPanelClass,
  avatarOrbClass,
  avatarMetaClass,
  heroCopyClass,
  eyebrowClass,
  titleClass,
  statusLineClass,
  metricGridClass,
  metricCardClass,
  metricLabelClass,
  metricValueClass,
  statusGridClass,
  cardClass,
  cardTitleClass,
  statListClass,
  progressTrackClass,
  progressFillClass,
  supportTextClass,
  badgeRowClass,
  badgeClass,
} as const;

export default styles;
