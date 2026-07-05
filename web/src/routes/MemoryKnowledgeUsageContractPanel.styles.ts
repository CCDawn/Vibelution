const styles = {
  contractDomainGrid:
    "contractDomainGrid min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  contractDomainRow:
    "contractDomainRow min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 !grid grid-cols-[minmax(116px,1fr)_minmax(96px,0.8fr)_auto] items-center gap-[3px] px-[5px] py-[3px]",
  contractForbiddenList:
    "contractForbiddenList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto hidden",
  contractPrinciples: "contractPrinciples min-w-0",
  contractStateGrid:
    "contractStateGrid min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))] hidden",
  countPill:
    "countPill min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  managementHeader:
    "managementHeader min-w-0 flex flex-wrap items-center gap-1.5",
  panelEyebrow:
    "panelEyebrow min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  usageContractPanel:
    "usageContractPanel min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
} as const;

export default styles;
