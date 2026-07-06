const styles = {
  operationDetails:
    "vui-components-conversationview operationDetails m-0 min-w-0 grid gap-1 border-0 border-l border-[color-mix(in_srgb,var(--accent-warm)_18%,var(--vui-border-subtle))] bg-transparent pl-2",
  operationDetailsThought:
    "vui-components-conversationview operationDetails_thought min-w-0",
  operationDetailRow:
    "vui-components-conversationview operationDetailRow grid min-w-0 grid-cols-[minmax(5.5rem,8rem)_minmax(0,1fr)] items-start gap-x-2 gap-y-0.5 border-b border-[color-mix(in_srgb,var(--accent-warm)_14%,var(--vui-border-subtle))] py-1 last:border-b-0 max-[560px]:grid-cols-[minmax(0,1fr)]",
  operationDetailLabel:
    "vui-components-conversationview operationDetailLabel min-w-0 pt-0.5 text-[var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-tertiary)] [overflow-wrap:anywhere]",
  operationDetailDescription:
    "vui-components-conversationview operationDetailDescription m-0 min-w-0",
  operationDetailValue:
    "vui-components-conversationview operationDetailValue m-0 min-w-0 max-w-full max-h-44 overflow-auto whitespace-pre-wrap break-words bg-transparent p-0 font-[var(--font-mono)] text-[var(--vui-font-xs)] leading-[1.45] text-[var(--fg-secondary)] [overflow-wrap:anywhere] focus-visible:rounded-[var(--radius-control)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)]",
} as const;

export default styles;
