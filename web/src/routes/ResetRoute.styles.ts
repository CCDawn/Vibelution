const routeClass = "grid h-full min-h-0 min-w-0 max-w-full grid-rows-[auto_minmax(0,1fr)] overflow-x-hidden";
const headerClass = "mx-2.5 mt-2 min-w-0 border-[color-mix(in_srgb,var(--vui-border-subtle)_78%,transparent)] bg-[var(--vui-gradient-route-soft),color-mix(in_srgb,var(--surface-panel)_70%,transparent)]";
const headerActionsClass = "flex flex-wrap items-center justify-end gap-2";
const secondaryButtonClass = "inline-flex w-fit max-w-full min-h-8 items-center justify-center gap-[7px] rounded-lg border border-vui-border-soft bg-[color-mix(in_srgb,var(--surface-card)_68%,transparent)] px-2.5 py-1.5 text-[var(--vui-font-xs)] text-vui-fg-secondary hover:border-[var(--border-strong)] hover:bg-[color-mix(in_srgb,var(--surface-panel-hover)_82%,transparent)] hover:text-vui-fg-primary";
const workspaceClass = "grid min-h-0 min-w-0 max-w-full grid-cols-[repeat(2,minmax(220px,360px))] items-start justify-start gap-2 overflow-x-hidden px-2.5 pb-2.5 pt-2 max-[720px]:grid-cols-[minmax(0,1fr)]";
const cardClass = "min-h-0 min-w-0 rounded-lg border border-[color-mix(in_srgb,var(--vui-border-subtle)_72%,transparent)] bg-[color-mix(in_srgb,var(--surface-panel)_62%,transparent)] p-2";
const cardTitleRowClass = "mb-1.5 flex items-center gap-1.5 text-vui-fg-primary";
const cardTitleClass = "m-0 text-[0.94rem] font-bold";
const subtitleClass = "m-0 min-w-0 truncate text-[var(--route-topbar-subtitle-size)] leading-[1.25] text-vui-fg-secondary";

const styles = {
  routeClass,
  headerClass,
  headerActionsClass,
  secondaryButtonClass,
  workspaceClass,
  cardClass,
  cardTitleRowClass,
  cardTitleClass,
  subtitleClass,
} as const;

export default styles;
