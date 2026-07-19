const panelSurface =
  "[background:color-mix(in_srgb,var(--surface-panel)_96%,var(--bg-canvas))] [border:1px_solid_var(--vui-border-subtle)] [border-radius:8px]";

const styles = {
  sectionSurface: `vui-routes-configproviderregistrypanel sectionSurface ${panelSurface} grid h-full min-h-0 min-w-0 [grid-template-rows:auto_minmax(0,1fr)] gap-3 overflow-hidden p-3`,
  header: "vui-routes-configproviderregistrypanel header min-w-0",
  registryWorkspace:
    "vui-routes-configproviderregistrypanel registryWorkspace h-full min-h-0 min-w-0 [--vui-workspace-sidebar:clamp(18rem,26vw,24rem)] gap-2 overflow-hidden",
  providerRail: "vui-routes-configproviderregistrypanel providerRail grid h-full min-h-0 min-w-0 [grid-template-rows:minmax(0,1fr)] gap-2",
  providerList: "vui-routes-configproviderregistrypanel providerList h-full min-h-0 min-w-0 overflow-y-auto pr-1",
  providerButton:
    "vui-routes-configproviderregistrypanel providerButton !grid !min-h-[58px] !w-full min-w-0 !grid-cols-[minmax(0,1fr)_auto] !justify-stretch gap-3 px-3 py-2 text-left",
  providerIdentity: "vui-routes-configproviderregistrypanel providerIdentity grid min-w-0 gap-0.5",
  ellipsis: "vui-routes-configproviderregistrypanel ellipsis min-w-0 truncate",
  detailSurface: "vui-routes-configproviderregistrypanel detailSurface grid h-full min-h-0 min-w-0 [grid-template-rows:auto_auto_auto_minmax(0,1fr)_auto_auto] gap-2 overflow-y-auto overflow-x-hidden pr-1",
  detailHeader:
    "vui-routes-configproviderregistrypanel detailHeader flex min-w-0 flex-wrap items-start justify-between gap-2 border-b border-vui-border-hairline pb-2",
  detailIdentity: "vui-routes-configproviderregistrypanel detailIdentity grid min-w-0 gap-0.5",
  tabs: "vui-routes-configproviderregistrypanel tabs flex min-w-0 flex-wrap items-center gap-1",
  tabButton: "vui-routes-configproviderregistrypanel tabButton",
  detailBody:
    "vui-routes-configproviderregistrypanel detailBody min-h-0 min-w-0 overflow-y-auto overflow-x-hidden rounded-lg border border-vui-border-subtle bg-vui-surface-row/40 p-2 [&>_*]:h-full",
  tabSurface: "vui-routes-configproviderregistrypanel tabSurface grid h-full min-h-0 min-w-0 content-start gap-2 overflow-auto",
  detailGrid:
    "vui-routes-configproviderregistrypanel detailGrid grid min-w-0 [grid-template-columns:repeat(2,minmax(0,1fr))] gap-2 max-[640px]:[grid-template-columns:minmax(0,1fr)]",
  fact: "vui-routes-configproviderregistrypanel fact grid min-w-0 gap-0.5 rounded-md border border-vui-border-subtle bg-vui-surface-row px-2 py-1.5",
  factLabel: "vui-routes-configproviderregistrypanel factLabel [font-size:var(--vui-font-xs)] font-semibold text-vui-fg-tertiary",
  factValue: "vui-routes-configproviderregistrypanel factValue min-w-0 truncate [font-size:var(--vui-font-sm)] font-semibold text-vui-fg-primary",
  deployment:
    "vui-routes-configproviderregistrypanel deployment grid min-w-0 gap-2 rounded-md border border-vui-border-subtle bg-vui-surface-glass p-2",
  modelsWorkspace: "vui-routes-configproviderregistrypanel modelsWorkspace grid h-full min-h-0 min-w-0 [grid-template-rows:auto_minmax(0,1fr)] gap-2 overflow-hidden",
  modelToolbar:
    "vui-routes-configproviderregistrypanel modelToolbar grid min-w-0 [grid-template-columns:minmax(16rem,0.7fr)_minmax(0,1fr)] items-center gap-2",
  modelSearch: "vui-routes-configproviderregistrypanel modelSearch min-w-0",
  modelFilters: "vui-routes-configproviderregistrypanel modelFilters flex min-w-0 flex-wrap items-center justify-end gap-1",
  tableScroll:
    "vui-routes-configproviderregistrypanel tableScroll h-full min-h-0 min-w-0 overflow-auto rounded-[var(--radius-control)]",
  table:
    "vui-routes-configproviderregistrypanel table min-w-[820px] !overflow-visible [&_thead]:sticky [&_thead]:top-0 [&_thead]:z-10",
  modelIdentity: "vui-routes-configproviderregistrypanel modelIdentity grid min-w-0 gap-0.5",
  modelActionState:
    "vui-routes-configproviderregistrypanel modelActionState inline-flex min-h-6 items-center rounded-full border border-vui-border-subtle bg-vui-surface-row/70 px-2 [font-size:var(--vui-font-xs)] font-semibold text-vui-fg-tertiary",
  capabilityList: "vui-routes-configproviderregistrypanel capabilityList flex min-w-0 flex-wrap gap-1",
  capabilityUnknown: "vui-routes-configproviderregistrypanel capabilityUnknown [font-size:var(--vui-font-xs)] text-vui-fg-tertiary",
  actions: "vui-routes-configproviderregistrypanel actions flex min-w-0 flex-wrap items-center gap-1.5",
  actionFeedback:
    "vui-routes-configproviderregistrypanel actionFeedback min-w-0 rounded-md border border-vui-border-subtle bg-vui-surface-row/70 px-2 py-1.5 [font-size:var(--vui-font-sm)] text-vui-fg-secondary [overflow-wrap:anywhere]",
  actionFeedbackError:
    "vui-routes-configproviderregistrypanel actionFeedbackError min-w-0 rounded-md border border-[color-mix(in_srgb,var(--state-error)_38%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-error)_8%,var(--vui-surface-row))] px-2 py-1.5 [font-size:var(--vui-font-sm)] text-[var(--state-error)] [overflow-wrap:anywhere]",
  mergeSection:
    "vui-routes-configproviderregistrypanel mergeSection min-w-0 rounded-lg border border-vui-border-subtle bg-vui-surface-row/40 p-2",
  mergeContent: "vui-routes-configproviderregistrypanel mergeContent grid min-w-0 gap-2",
  mergeFacts:
    "vui-routes-configproviderregistrypanel mergeFacts flex min-w-0 flex-wrap items-center gap-2 [font-size:var(--vui-font-xs)] text-vui-fg-secondary",
  mergeConfirmation:
    "vui-routes-configproviderregistrypanel mergeConfirmation flex min-w-0 items-start gap-2 rounded-md border border-vui-border-subtle bg-vui-surface-panel px-2 py-1.5 [font-size:var(--vui-font-sm)] text-vui-fg-secondary [&_input]:mt-0.5",
  dangerZone:
    "vui-routes-configproviderregistrypanel dangerZone flex min-w-0 items-center justify-between gap-3 border-t border-[color-mix(in_srgb,var(--state-error)_22%,var(--vui-border-subtle))] pt-2",
  critical:
    "vui-routes-configproviderregistrypanel critical rounded-md border border-[color-mix(in_srgb,var(--state-error)_38%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-error)_8%,var(--vui-surface-row))] px-2 py-1.5 [font-size:var(--vui-font-sm)] text-[var(--state-error)]",
  muted: "vui-routes-configproviderregistrypanel muted [font-size:var(--vui-font-xs)] text-vui-fg-tertiary",
};

export default styles;
