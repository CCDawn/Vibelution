const panelSurface =
  "[background:var(--vui-surface-panel)] [border:1px_solid_var(--vui-border-subtle)] [border-radius:8px]";

const styles = {
  actions: "vui-routes-configmodelmigrationpanel actions flex min-w-0 flex-wrap items-center gap-1.5",
  conflictList: "vui-routes-configmodelmigrationpanel conflictList m-0 grid min-w-0 gap-1 pl-5 [font-size:var(--vui-font-sm)] text-[var(--state-error)]",
  critical:
    "vui-routes-configmodelmigrationpanel critical rounded-md border border-[color-mix(in_srgb,var(--state-error)_38%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-error)_8%,var(--vui-surface-row))] px-2 py-1.5 [font-size:var(--vui-font-sm)] text-[var(--state-error)]",
  fact: "vui-routes-configmodelmigrationpanel fact grid min-w-0 gap-0.5 rounded-md border border-vui-border-subtle bg-vui-surface-row px-2 py-1.5",
  migration: `vui-routes-configmodelmigrationpanel migration ${panelSurface} grid min-w-0 gap-3 p-3`,
  migrationSummary: "vui-routes-configmodelmigrationpanel migrationSummary grid min-w-0 [grid-template-columns:repeat(3,minmax(0,1fr))] gap-2 max-[640px]:[grid-template-columns:minmax(0,1fr)]",
  muted: "vui-routes-configmodelmigrationpanel muted [font-size:var(--vui-font-xs)] text-vui-fg-tertiary",
  resolutionActions: "vui-routes-configmodelmigrationpanel resolutionActions flex min-w-0 flex-wrap items-center gap-1.5",
  resolutionCard: "vui-routes-configmodelmigrationpanel resolutionCard grid min-w-0 gap-2 [overflow-wrap:anywhere] rounded-md border border-vui-border-subtle bg-vui-surface-row p-2",
  resolutionCardHeader: "vui-routes-configmodelmigrationpanel resolutionCardHeader flex min-w-0 flex-wrap items-center justify-between gap-2",
  resolutionError: "vui-routes-configmodelmigrationpanel resolutionError m-0 min-w-0 [font-size:var(--vui-font-xs)] text-[var(--state-error)]",
  resolutionFields: "vui-routes-configmodelmigrationpanel resolutionFields grid min-w-0 [grid-template-columns:minmax(0,1fr)] gap-2 max-[390px]:[grid-template-columns:minmax(0,1fr)]",
  resolutionGrid: "vui-routes-configmodelmigrationpanel resolutionGrid grid min-w-0 [grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr))] gap-2",
  resolutionHeading: "vui-routes-configmodelmigrationpanel resolutionHeading flex min-w-0 flex-wrap items-baseline justify-between gap-2",
  resolutionSection: "vui-routes-configmodelmigrationpanel resolutionSection grid min-w-0 gap-2 rounded-md border border-[color-mix(in_srgb,var(--state-warning)_42%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-warning)_6%,var(--vui-surface-panel))] p-2",
  resolutionWarning: "vui-routes-configmodelmigrationpanel resolutionWarning m-0 min-w-0 [font-size:var(--vui-font-xs)] text-[var(--state-warning)]",
  table: "vui-routes-configmodelmigrationpanel table min-w-[760px]",
  tableScroll: "vui-routes-configmodelmigrationpanel tableScroll min-w-0 [overflow-x:auto]",
};

export default styles;
