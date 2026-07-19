const styles = {
  leftBlock:
    "vui-routes-chatcodingroute leftBlock grid min-w-0 shrink-0 gap-1.5 border-0 border-b border-[var(--vui-border-subtle)] bg-transparent p-2 shadow-none last:border-b-0",
  llmPayloadTraceGrid:
    "vui-routes-chatcodingroute llmPayloadTraceGrid grid min-w-0 grid-cols-2 gap-2",
  llmPayloadTraceHelp:
    "vui-routes-chatcodingroute llmPayloadTraceHelp grid h-5 w-5 place-items-center rounded-full border border-[var(--vui-border-subtle)] [font-size:var(--vui-font-xs)] font-semibold text-[var(--fg-tertiary)]",
  llmPayloadTraceItem:
    "vui-routes-chatcodingroute llmPayloadTraceItem grid min-w-0 gap-0.5 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--vui-border-subtle)_76%,transparent)] bg-[color-mix(in_srgb,var(--vui-surface-row)_46%,transparent)] px-2 py-1 [font-size:var(--vui-font-xs)] leading-tight [&_strong]:min-w-0 [&_strong]:truncate [&_strong]:font-semibold [&_strong]:text-[var(--fg-primary)]",
  llmPayloadTraceMuted:
    "vui-routes-chatcodingroute llmPayloadTraceMuted min-w-0 truncate text-[var(--fg-tertiary)]",
  llmPayloadTracePanel:
    "vui-routes-chatcodingroute llmPayloadTracePanel min-w-0",
  sectionHeader:
    "vui-routes-chatcodingroute sectionHeader min-w-0 !grid grid-cols-[minmax(0,1fr)_max-content] items-start gap-1.5",
  sectionTitle:
    "vui-routes-chatcodingroute sectionTitle min-w-0 [font-size:var(--vui-font-title)] font-semibold leading-tight text-[var(--fg-primary)] m-0",
} as const;

export default styles;
