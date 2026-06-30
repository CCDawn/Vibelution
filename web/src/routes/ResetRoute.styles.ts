const routeClass = "grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)] bg-[var(--surface-page)]";
const headerClass = "mx-2.5 mt-2 min-w-0 border-[var(--vui-border-subtle)] bg-[var(--vui-gradient-route-soft),color-mix(in_srgb,var(--surface-panel)_86%,transparent)] shadow-[var(--vui-shadow-hairline)]";
const headerActionsClass = "flex items-center justify-end gap-2";
const secondaryButtonClass = "inline-flex min-h-8 items-center justify-center gap-[7px] rounded-lg border border-vui-border-soft bg-[var(--surface-card)] px-2.5 py-1.5 text-[var(--vui-font-xs)] text-vui-fg-secondary hover:border-[var(--border-strong)] hover:bg-[var(--surface-panel-hover)] hover:text-vui-fg-primary";
const workspaceClass = "grid min-h-0 grid-cols-[minmax(0,1fr)_minmax(320px,390px)] items-start gap-2 px-2.5 pb-2.5 pt-2 max-[1120px]:grid-cols-1";
const cardClass = "min-h-0 rounded-lg border border-vui-border-soft bg-[var(--surface-panel)] p-2";
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
