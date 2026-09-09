const styles = {
  templateButton: "!h-auto !min-h-16 !w-full !justify-start !text-left !px-3 !py-3 [&_strong]:whitespace-normal [&_strong]:break-words",
  critical:
    "vui-routes-configproviderwizard critical rounded-md border border-[color-mix(in_srgb,var(--state-error)_38%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-error)_8%,var(--vui-surface-row))] px-2 py-1.5 [font-size:var(--vui-font-sm)] text-[var(--state-error)]",
  discoveryGrid: "vui-routes-configproviderwizard discoveryGrid grid min-w-0 gap-1.5",
  ellipsis: "vui-routes-configproviderwizard ellipsis min-w-0 whitespace-normal break-words",
  field: "vui-routes-configproviderwizard field grid min-w-0 gap-1 [font-size:var(--vui-font-xs)] font-semibold text-vui-fg-secondary",
  fieldGrid: "vui-routes-configproviderwizard fieldGrid grid min-w-0 [grid-template-columns:repeat(2,minmax(0,1fr))] gap-2 max-[640px]:[grid-template-columns:minmax(0,1fr)]",
  fieldWide: "vui-routes-configproviderwizard fieldWide col-span-full grid min-w-0 gap-1 max-[640px]:col-span-1",
  modelIdentity: "vui-routes-configproviderwizard modelIdentity grid min-w-0 gap-0.5",
  muted: "vui-routes-configproviderwizard muted [font-size:var(--vui-font-xs)] text-vui-fg-tertiary",
  protocolGrid: "vui-routes-configproviderwizard protocolGrid flex min-w-0 flex-wrap gap-1.5",
  providerIdentity: "vui-routes-configproviderwizard providerIdentity grid min-w-0 gap-0.5",
  templateGrid: "vui-routes-configproviderwizard templateGrid grid min-w-0 grid-cols-[repeat(auto-fill,minmax(15rem,1fr))] gap-2",
  templateGroup: "vui-routes-configproviderwizard templateGroup grid min-w-0 grid-cols-[8rem_minmax(0,1fr)] content-start gap-4 border-t border-vui-border-subtle pt-4",
  templateGroups: "vui-routes-configproviderwizard templateGroups grid min-w-0 gap-4",
  wizard: "vui-routes-configproviderwizard wizard grid w-full max-w-[90rem] min-w-0 gap-5 !border-0 !bg-transparent !p-4",
  wizardBody: "vui-routes-configproviderwizard wizardBody grid min-w-0 gap-2",
  wizardFooter: "vui-routes-configproviderwizard wizardFooter flex min-w-0 flex-wrap items-center justify-between gap-2 border-t border-vui-border-hairline pt-2",
  wizardSteps: "vui-routes-configproviderwizard wizardSteps flex flex-wrap gap-2",
};

export default styles;
