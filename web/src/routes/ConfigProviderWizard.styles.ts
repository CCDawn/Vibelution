const panelSurface =
  "[background:color-mix(in_srgb,var(--surface-panel)_96%,var(--bg-canvas))] [border:1px_solid_var(--vui-border-subtle)] [border-radius:8px]";

const styles = {
  critical:
    "vui-routes-configproviderwizard critical rounded-md border border-[color-mix(in_srgb,var(--state-error)_38%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-error)_8%,var(--vui-surface-row))] px-2 py-1.5 [font-size:var(--vui-font-sm)] text-[var(--state-error)]",
  discoveryGrid: "vui-routes-configproviderwizard discoveryGrid grid min-w-0 gap-1.5",
  ellipsis: "vui-routes-configproviderwizard ellipsis min-w-0 truncate",
  field: "vui-routes-configproviderwizard field grid min-w-0 gap-1 [font-size:var(--vui-font-xs)] font-semibold text-vui-fg-secondary",
  fieldGrid: "vui-routes-configproviderwizard fieldGrid grid min-w-0 [grid-template-columns:repeat(2,minmax(0,1fr))] gap-2 max-[640px]:[grid-template-columns:minmax(0,1fr)]",
  fieldWide: "vui-routes-configproviderwizard fieldWide col-span-full grid min-w-0 gap-1 max-[640px]:col-span-1",
  modelIdentity: "vui-routes-configproviderwizard modelIdentity grid min-w-0 gap-0.5",
  muted: "vui-routes-configproviderwizard muted [font-size:var(--vui-font-xs)] text-vui-fg-tertiary",
  protocolGrid: "vui-routes-configproviderwizard protocolGrid flex min-w-0 flex-wrap gap-1.5",
  providerIdentity: "vui-routes-configproviderwizard providerIdentity grid min-w-0 gap-0.5",
  templateGrid: "vui-routes-configproviderwizard templateGrid grid min-w-0 [grid-template-columns:repeat(auto-fit,minmax(150px,1fr))] gap-1",
  templateGroup: "vui-routes-configproviderwizard templateGroup grid min-w-0 content-start gap-1.5 rounded-md border border-vui-border-subtle bg-vui-surface-row p-2",
  templateGroups: "vui-routes-configproviderwizard templateGroups grid min-w-0 [grid-template-columns:repeat(2,minmax(0,1fr))] gap-2 max-[720px]:[grid-template-columns:minmax(0,1fr)]",
  wizard: `vui-routes-configproviderwizard wizard ${panelSurface} grid min-w-0 gap-3 p-3`,
  wizardBody: "vui-routes-configproviderwizard wizardBody grid min-w-0 gap-2",
  wizardFooter: "vui-routes-configproviderwizard wizardFooter flex min-w-0 flex-wrap items-center justify-between gap-2 border-t border-vui-border-hairline pt-2",
  wizardSteps: "vui-routes-configproviderwizard wizardSteps grid min-w-0 [grid-template-columns:repeat(4,minmax(0,1fr))] gap-1 max-[640px]:[grid-template-columns:repeat(2,minmax(0,1fr))]",
};

export default styles;
