const panelSurface =
  "[background:color-mix(in_srgb,var(--surface-panel)_96%,var(--bg-canvas))] [border:1px_solid_var(--vui-border-subtle)] [border-radius:8px]";

const styles = {
  sectionSurface: `vui-routes-configproviderregistrypanel sectionSurface ${panelSurface} grid min-w-0 gap-3 p-3`,
  header: "vui-routes-configproviderregistrypanel header min-w-0",
  registryWorkspace:
    "vui-routes-configproviderregistrypanel registryWorkspace grid min-w-0 [grid-template-columns:minmax(220px,0.34fr)_minmax(0,1fr)] gap-2 max-[960px]:[grid-template-columns:minmax(0,1fr)]",
  providerRail: "vui-routes-configproviderregistrypanel providerRail grid min-w-0 content-start gap-2",
  providerList: "vui-routes-configproviderregistrypanel providerList max-h-[34rem] min-w-0 overflow-y-auto",
  providerButton:
    "vui-routes-configproviderregistrypanel providerButton !grid !w-full min-w-0 !grid-cols-[minmax(0,1fr)_auto] !justify-stretch gap-2 text-left",
  providerIdentity: "vui-routes-configproviderregistrypanel providerIdentity grid min-w-0 gap-0.5",
  ellipsis: "vui-routes-configproviderregistrypanel ellipsis min-w-0 truncate",
  detailSurface: "vui-routes-configproviderregistrypanel detailSurface grid min-w-0 content-start gap-2",
  detailHeader:
    "vui-routes-configproviderregistrypanel detailHeader flex min-w-0 flex-wrap items-start justify-between gap-2 border-b border-vui-border-hairline pb-2",
  detailIdentity: "vui-routes-configproviderregistrypanel detailIdentity grid min-w-0 gap-0.5",
  tabs: "vui-routes-configproviderregistrypanel tabs flex min-w-0 flex-wrap items-center gap-1",
  tabButton: "vui-routes-configproviderregistrypanel tabButton",
  detailGrid:
    "vui-routes-configproviderregistrypanel detailGrid grid min-w-0 [grid-template-columns:repeat(2,minmax(0,1fr))] gap-2 max-[640px]:[grid-template-columns:minmax(0,1fr)]",
  fact: "vui-routes-configproviderregistrypanel fact grid min-w-0 gap-0.5 rounded-md border border-vui-border-subtle bg-vui-surface-row px-2 py-1.5",
  factLabel: "vui-routes-configproviderregistrypanel factLabel text-[var(--vui-font-xs)] font-semibold text-vui-fg-tertiary",
  factValue: "vui-routes-configproviderregistrypanel factValue min-w-0 truncate text-[var(--vui-font-sm)] font-semibold text-vui-fg-primary",
  deployment:
    "vui-routes-configproviderregistrypanel deployment grid min-w-0 gap-2 rounded-md border border-vui-border-subtle bg-vui-surface-glass p-2",
  tableScroll: "vui-routes-configproviderregistrypanel tableScroll min-w-0 [overflow-x:auto]",
  table: "vui-routes-configproviderregistrypanel table min-w-[760px]",
  modelIdentity: "vui-routes-configproviderregistrypanel modelIdentity grid min-w-0 gap-0.5",
  capabilityList: "vui-routes-configproviderregistrypanel capabilityList flex min-w-0 flex-wrap gap-1",
  actions: "vui-routes-configproviderregistrypanel actions flex min-w-0 flex-wrap items-center gap-1.5",
  mobileActionGroup:
    "vui-routes-configproviderregistrypanel mobileActionGroup grid min-w-0 [grid-template-columns:repeat(auto-fit,minmax(max-content,1fr))] gap-1.5 max-[390px]:[grid-template-columns:minmax(0,1fr)] max-[390px]:[&_[data-vui=button]]:!w-full",
  critical:
    "vui-routes-configproviderregistrypanel critical rounded-md border border-[color-mix(in_srgb,var(--state-error)_38%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-error)_8%,var(--vui-surface-row))] px-2 py-1.5 text-[var(--vui-font-sm)] text-[var(--state-error)]",
  muted: "vui-routes-configproviderregistrypanel muted text-[var(--vui-font-xs)] text-vui-fg-tertiary",
  wizard: `vui-routes-configproviderregistrypanel wizard ${panelSurface} grid min-w-0 gap-3 p-3`,
  wizardSteps: "vui-routes-configproviderregistrypanel wizardSteps grid min-w-0 [grid-template-columns:repeat(4,minmax(0,1fr))] gap-1 max-[640px]:[grid-template-columns:repeat(2,minmax(0,1fr))]",
  wizardBody: "vui-routes-configproviderregistrypanel wizardBody grid min-w-0 gap-2",
  templateGroups: "vui-routes-configproviderregistrypanel templateGroups grid min-w-0 [grid-template-columns:repeat(2,minmax(0,1fr))] gap-2 max-[720px]:[grid-template-columns:minmax(0,1fr)]",
  templateGroup: "vui-routes-configproviderregistrypanel templateGroup grid min-w-0 content-start gap-1.5 rounded-md border border-vui-border-subtle bg-vui-surface-row p-2",
  templateGrid: "vui-routes-configproviderregistrypanel templateGrid grid min-w-0 [grid-template-columns:repeat(auto-fit,minmax(150px,1fr))] gap-1",
  fieldGrid: "vui-routes-configproviderregistrypanel fieldGrid grid min-w-0 [grid-template-columns:repeat(2,minmax(0,1fr))] gap-2 max-[640px]:[grid-template-columns:minmax(0,1fr)]",
  field: "vui-routes-configproviderregistrypanel field grid min-w-0 gap-1 text-[var(--vui-font-xs)] font-semibold text-vui-fg-secondary",
  fieldWide: "vui-routes-configproviderregistrypanel fieldWide col-span-full grid min-w-0 gap-1 max-[640px]:col-span-1",
  protocolGrid: "vui-routes-configproviderregistrypanel protocolGrid flex min-w-0 flex-wrap gap-1.5",
  discoveryGrid: "vui-routes-configproviderregistrypanel discoveryGrid grid min-w-0 gap-1.5",
  wizardFooter: "vui-routes-configproviderregistrypanel wizardFooter flex min-w-0 flex-wrap items-center justify-between gap-2 border-t border-vui-border-hairline pt-2",
  migration: `vui-routes-configproviderregistrypanel migration ${panelSurface} grid min-w-0 gap-3 p-3`,
  migrationSummary: "vui-routes-configproviderregistrypanel migrationSummary grid min-w-0 [grid-template-columns:repeat(3,minmax(0,1fr))] gap-2 max-[640px]:[grid-template-columns:minmax(0,1fr)]",
  conflictList: "vui-routes-configproviderregistrypanel conflictList m-0 grid min-w-0 gap-1 pl-5 text-[var(--vui-font-sm)] text-[var(--state-error)]",
};

export default styles;
