const rowGrid = "grid min-w-0 grid-cols-[8px_minmax(0,1fr)_auto_auto_auto_12px] items-center gap-1.5";

const styles: Record<string, string> = {
  root:
    "vui-components-conversation-composercontextring root relative inline-flex shrink-0",
  trigger:
    "vui-components-conversation-composercontextring trigger !inline-flex !size-[30px] !h-[30px] !w-[30px] !min-h-0 !min-w-0 !items-center !justify-center !overflow-hidden !rounded-full !border-0 !border-transparent !bg-transparent !p-0 !shadow-none !outline-none hover:!border-transparent hover:!bg-[color-mix(in_srgb,var(--vui-control-muted)_70%,transparent)] hover:!shadow-none focus-visible:!outline-none focus-visible:!ring-2 focus-visible:!ring-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] focus-visible:!ring-offset-0 data-[state=open]:!border-transparent data-[state=open]:!bg-[color-mix(in_srgb,var(--vui-control-muted)_55%,transparent)] data-[state=open]:!shadow-none",
  ring:
    "vui-components-conversation-composercontextring ringGraphic block size-7 overflow-visible",
  popover:
    "vui-components-conversation-composercontextring popover grid w-[min(320px,calc(100vw-48px))] gap-2 !p-2.5",
  head:
    "vui-components-conversation-composercontextring head flex min-w-0 items-baseline justify-between gap-2",
  title:
    "vui-components-conversation-composercontextring title text-[12px] font-bold leading-none text-vui-fg-primary",
  nums:
    "vui-components-conversation-composercontextring nums min-w-0 truncate text-[11px] font-semibold tabular-nums leading-none text-[var(--fg-secondary)] [&_b]:font-bold [&_b]:text-vui-fg-primary",
  compositionSection:
    "vui-components-conversation-composercontextring compositionSection grid gap-1",
  sectionTitle:
    "vui-components-conversation-composercontextring sectionTitle text-[10px] font-bold leading-none text-[var(--fg-tertiary)]",
  stack:
    "vui-components-conversation-composercontextring stack grid gap-1",
  hitEdge:
    "vui-components-conversation-composercontextring hitEdge flex h-1.5 overflow-hidden rounded-full bg-[color-mix(in_srgb,var(--vui-border-subtle)_85%,transparent)]",
  hitSeg:
    "vui-components-conversation-composercontextring hitSeg block h-full min-w-0",
  hitSeg_hit:
    "vui-components-conversation-composercontextring hitSeg_hit bg-[var(--accent-cool)]",
  hitSeg_miss:
    "vui-components-conversation-composercontextring hitSeg_miss bg-[var(--accent-warm)]",
  hitSeg_never:
    "vui-components-conversation-composercontextring hitSeg_never bg-[repeating-linear-gradient(90deg,color-mix(in_srgb,var(--fg-tertiary)_55%,transparent)_0_3px,transparent_3px_6px)]",
  hitSeg_unknown:
    "vui-components-conversation-composercontextring hitSeg_unknown bg-[color-mix(in_srgb,var(--fg-tertiary)_35%,transparent)]",
  compBar:
    "vui-components-conversation-composercontextring compBar flex h-2.5 overflow-hidden rounded-full bg-[color-mix(in_srgb,var(--vui-border-subtle)_85%,transparent)]",
  compSeg:
    "vui-components-conversation-composercontextring compSeg block h-full min-w-0",
  rows:
    "vui-components-conversation-composercontextring rows grid max-h-[min(16rem,42vh)] content-start gap-0.5 overflow-y-auto overscroll-contain",
  rowGroup:
    "vui-components-conversation-composercontextring rowGroup grid min-w-0",
  row:
    `${rowGrid} vui-components-conversation-composercontextring row rounded-[6px] px-1 py-0.5 text-[11px] hover:bg-[color-mix(in_srgb,var(--vui-control-muted)_55%,transparent)]`,
  rowEmpty:
    "vui-components-conversation-composercontextring rowEmpty grid min-w-0 grid-cols-[8px_minmax(0,1fr)_auto] items-center gap-1.5 rounded-[6px] px-1 py-0.5 text-[11px]",
  rowButton:
    `${rowGrid} vui-components-conversation-composercontextring rowButton !h-auto !min-h-0 !w-full !cursor-pointer !justify-start !gap-1.5 !rounded-[6px] !border-0 !border-transparent !bg-transparent !px-1 !py-0.5 !text-left !text-[11px] !font-normal !leading-tight !shadow-none hover:!bg-[color-mix(in_srgb,var(--vui-control-muted)_55%,transparent)] focus-visible:!outline-none focus-visible:!ring-1 focus-visible:!ring-[color-mix(in_srgb,var(--accent-cool)_30%,transparent)]`,
  swatch:
    "vui-components-conversation-composercontextring swatch size-2 shrink-0 rounded-[2px]",
  rowName:
    "vui-components-conversation-composercontextring rowName min-w-0 truncate text-[var(--fg-secondary)]",
  rowPct:
    "vui-components-conversation-composercontextring rowPct shrink-0 text-[10px] font-semibold tabular-nums text-[var(--fg-tertiary)]",
  rowValue:
    "vui-components-conversation-composercontextring rowValue shrink-0 font-semibold tabular-nums text-vui-fg-primary",
  rowBadge:
    "vui-components-conversation-composercontextring rowBadge inline-flex shrink-0 items-center rounded-[4px] px-1 text-[10px] font-semibold leading-4",
  rowBadge_hit:
    "vui-components-conversation-composercontextring rowBadge_hit bg-[color-mix(in_srgb,var(--accent-cool)_12%,transparent)] text-[var(--accent-cool)]",
  rowBadge_miss:
    "vui-components-conversation-composercontextring rowBadge_miss bg-[color-mix(in_srgb,var(--accent-warm)_14%,transparent)] text-[var(--accent-warm)]",
  rowBadge_never:
    "vui-components-conversation-composercontextring rowBadge_never bg-[color-mix(in_srgb,var(--vui-control-muted)_75%,transparent)] text-[var(--fg-tertiary)]",
  rowBadge_unknown:
    "vui-components-conversation-composercontextring rowBadge_unknown border border-dashed border-[color-mix(in_srgb,var(--fg-tertiary)_40%,transparent)] text-[var(--fg-tertiary)]",
  rowChevron:
    "vui-components-conversation-composercontextring rowChevron size-3 shrink-0 text-[var(--fg-tertiary)] transition-transform",
  rowChevronOpen:
    "vui-components-conversation-composercontextring rowChevronOpen rotate-180",
  rowPreview:
    "vui-components-conversation-composercontextring rowPreview mt-0.5 max-h-24 overflow-y-auto whitespace-pre-wrap break-words rounded-[6px] border border-[var(--vui-border-subtle)] bg-[color-mix(in_srgb,var(--vui-control-muted)_65%,transparent)] px-1.5 py-1 text-[10px] leading-snug text-[var(--fg-secondary)]",
  cacheSection:
    "vui-components-conversation-composercontextring cacheSection grid gap-1 border-t border-[var(--vui-border-subtle)] pt-1.5",
  cacheHead:
    "vui-components-conversation-composercontextring cacheHead flex min-w-0 items-baseline justify-between gap-2",
  cacheHeadline:
    "vui-components-conversation-composercontextring cacheHeadline min-w-0 truncate text-[10px] font-semibold tabular-nums leading-none text-[var(--fg-secondary)]",
  cacheLegend:
    "vui-components-conversation-composercontextring cacheLegend flex flex-wrap items-center gap-x-2 gap-y-0.5",
  cacheLegendItem:
    "vui-components-conversation-composercontextring cacheLegendItem inline-flex items-center gap-1 text-[10px] font-semibold leading-tight text-[var(--fg-tertiary)]",
  legendDot:
    "vui-components-conversation-composercontextring legendDot size-1.5 shrink-0 rounded-full",
  legendDot_hit:
    "vui-components-conversation-composercontextring legendDot_hit bg-[var(--accent-cool)]",
  legendDot_miss:
    "vui-components-conversation-composercontextring legendDot_miss bg-[var(--accent-warm)]",
  legendDot_never:
    "vui-components-conversation-composercontextring legendDot_never bg-[repeating-linear-gradient(90deg,color-mix(in_srgb,var(--fg-tertiary)_55%,transparent)_0_2px,transparent_2px_4px)]",
  legendDot_unknown:
    "vui-components-conversation-composercontextring legendDot_unknown bg-[color-mix(in_srgb,var(--fg-tertiary)_35%,transparent)]",
  foot:
    "vui-components-conversation-composercontextring foot flex min-w-0 items-center justify-between gap-2 border-t border-[var(--vui-border-subtle)] pt-1.5",
  hint:
    "vui-components-conversation-composercontextring hint min-w-0 flex-1 truncate text-[10px] font-semibold leading-tight text-[var(--fg-tertiary)]",
  detailLink:
    "vui-components-conversation-composercontextring detailLink !h-auto !min-h-0 !border-0 !bg-transparent !p-0 !text-[11px] !font-semibold !text-[var(--accent-cool)] !shadow-none hover:!underline",
};

export default styles;
