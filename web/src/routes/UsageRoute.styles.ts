const styles = {
  outputSegment: "flex-1",
  page: "h-full min-h-0 min-w-0 max-w-full overflow-y-auto overflow-x-hidden bg-vui-surface-canvas px-4 py-5 max-[700px]:px-2 max-[700px]:py-2",
  sheet: "mx-auto w-full max-w-[1120px] min-w-0 rounded-vui-panel border border-vui-border-subtle bg-vui-surface-panel px-10 py-7 max-[700px]:px-4 max-[700px]:py-4",
  breadcrumb: "mb-6 flex min-w-0 items-center gap-2 text-vui-xs text-vui-fg-tertiary [&_a]:!p-0 [&_a]:!bg-transparent [&_a]:!border-0",
  recipe: "!h-auto !overflow-visible !bg-transparent",
  header: "[&_[data-vui=route-header]]:!border-0 [&_[data-vui=route-header]]:!bg-transparent [&_[data-vui=route-header]]:!p-0 [&_[data-vui=route-header]]:!shadow-none [&_[data-vui=route-header]]:!backdrop-blur-none [&_h1]:!text-[24px] [&_h1]:!font-semibold [&_h1+span]:!font-normal [&_h1+span]:!whitespace-normal [&_[data-vui=route-header]>div:first-child>div]:!flex-col [&_[data-vui=route-header]>div:first-child>div]:!items-start",
  body: "!block !overflow-visible",
  rangeRow: "mt-7 flex min-w-0 flex-wrap items-center justify-between gap-3 [&>span]:text-vui-xs [&>span]:text-vui-fg-tertiary",
  metrics: "my-7 grid min-w-0 grid-cols-[1.25fr_1fr_1fr] gap-6 border-b border-vui-border-subtle pb-7 max-[700px]:grid-cols-2 [&>div:first-child]:border-0 [&>div:first-child]:pl-0 max-[700px]:[&>div:first-child]:col-span-2 max-[700px]:[&>div:nth-child(2)]:border-0 max-[700px]:[&>div:nth-child(2)]:pl-0",
  metric: "flex min-w-0 min-h-[96px] flex-col gap-2 border-l border-vui-border-subtle pl-6 [&>span]:text-vui-xs [&>span]:text-vui-fg-secondary [&>strong]:break-words [&>strong]:text-[clamp(20px,2.2vw,30px)] [&>strong]:font-semibold [&>strong]:tabular-nums [&>small]:text-[11px] [&>small]:text-vui-fg-tertiary",
  sectionHeading: "mb-4 flex min-w-0 items-start justify-between gap-3 [&>h2]:m-0 [&>h2]:text-vui-sm [&>h2]:font-semibold [&>span]:text-[11px] [&>span]:text-vui-fg-tertiary [&>span]:text-right",
  composition: "mb-4 flex h-1.5 min-w-0 overflow-hidden rounded-full gap-0.5 [&>span:first-child]:bg-[var(--accent-cool)] [&>span:last-child]:bg-[var(--state-success)]",
  tokenRow: "flex min-w-0 items-center justify-between gap-3 border-b border-vui-border-subtle py-3 text-vui-xs [&>div]:flex [&>div]:min-w-0 [&>div]:items-center [&>div]:gap-5 [&_strong]:font-medium [&>div>span]:text-[11px] [&>div>span]:text-vui-fg-tertiary max-[700px]:[&>div>span]:hidden [&>span]:shrink-0 [&>span]:tabular-nums",
  subset: "pl-4 text-vui-fg-tertiary",
  sources: "mt-7",
  sourceRow: "grid min-w-0 grid-cols-[1fr_auto_1fr] items-center gap-x-5 gap-y-1 py-2 text-vui-xs [&>span:first-child]:text-vui-fg-secondary [&>strong]:font-medium [&>strong]:tabular-nums [&>strong]:text-right [&>span:last-child]:text-right [&>span:last-child]:text-[11px] [&>span:last-child]:text-vui-fg-tertiary max-[700px]:grid-cols-[1fr_auto] max-[700px]:[&>span:last-child]:col-span-2 max-[700px]:[&>span:last-child]:text-left",
  diagnostics: "mt-6 border-t border-vui-border-subtle pt-3",
  diagnosticsToggle: "!w-full !justify-start !border-0 !bg-transparent !px-0 !shadow-none !font-normal !text-vui-xs !text-vui-fg-secondary [&>small]:ml-auto [&>small]:text-vui-fg-tertiary max-[700px]:[&>small]:hidden",
  details: "m-0 mt-3 rounded-vui-panel bg-vui-surface-row p-4 [&>div]:grid [&>div]:min-w-0 [&>div]:grid-cols-[140px_minmax(0,1fr)] [&>div]:gap-3 [&>div]:py-2 [&>div]:text-vui-xs [&_dt]:text-vui-fg-tertiary [&_dd]:m-0 [&_dd]:[overflow-wrap:anywhere] max-[700px]:[&>div]:grid-cols-[85px_minmax(0,1fr)]",
  note: "mb-0 mt-5 text-[11px] leading-relaxed text-vui-fg-tertiary",
} as const;

export default styles;
