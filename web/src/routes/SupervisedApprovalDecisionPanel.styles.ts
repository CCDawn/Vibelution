import {
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
} from "../design/vuiSurfaceRecipes";

const borderedSurface =
  `rounded-lg border border-[var(--vui-border-subtle)] ${vuiOpaqueRowClass}`;

const styles = {
  actionBar:
    "flex min-w-0 flex-wrap items-center justify-between gap-2 border-t border-[var(--vui-border-subtle)] pt-2.5 max-[560px]:items-stretch max-[560px]:[&>button]:w-full",
  actionCard:
    `grid min-w-0 content-start gap-1.5 ${borderedSurface} p-2.5 data-[status=active]:border-[color-mix(in_srgb,var(--accent-cool)_42%,var(--vui-border-subtle))] data-[status=blocked]:border-[color-mix(in_srgb,var(--state-error)_36%,var(--vui-border-subtle))] data-[status=done]:border-[color-mix(in_srgb,var(--state-success)_32%,var(--vui-border-subtle))] [&_p]:m-0 [&_p]:text-[length:var(--vui-font-xs)] [&_p]:leading-[1.45] [&_p]:text-[var(--fg-secondary)] [&_small]:text-[length:var(--vui-font-xs)] [&_small]:leading-[1.4] [&_small]:text-[var(--fg-tertiary)]`,
  actionCardHeader:
    "flex min-w-0 items-start justify-between gap-2 [&_strong]:min-w-0 [&_strong]:text-[length:var(--vui-font-xs)] [&_strong]:text-[var(--fg-primary)]",
  actionPath:
    "grid min-w-0 grid-cols-1 gap-2 @min-[720px]:grid-cols-3",
  actionSection:
    "grid min-w-0 gap-2",
  actionSectionHeading:
    "m-0 text-[length:var(--vui-font-sm)] font-semibold text-[var(--fg-primary)]",
  blockerList:
    "m-0 grid min-w-0 gap-1 rounded-lg border border-[color-mix(in_srgb,var(--state-error)_34%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-error)_6%,var(--vui-surface-row))] px-3 py-2 pl-7 text-[length:var(--vui-font-xs)] leading-[1.45] text-[var(--fg-secondary)]",
  bodyGrid:
    "grid min-w-0 grid-cols-1 gap-2 @min-[680px]:grid-cols-[minmax(0,1.2fr)_minmax(230px,0.8fr)]",
  decisionBanner:
    `grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-lg border border-[var(--vui-border-subtle)] ${vuiFlatPanelClass} px-3 py-2.5 data-[tone=warning]:border-[color-mix(in_srgb,var(--state-warning)_42%,var(--vui-border-subtle))] data-[tone=success]:border-[color-mix(in_srgb,var(--state-success)_34%,var(--vui-border-subtle))] data-[tone=danger]:border-[color-mix(in_srgb,var(--state-error)_38%,var(--vui-border-subtle))] data-[tone=info]:border-[color-mix(in_srgb,var(--accent-cool)_38%,var(--vui-border-subtle))] @max-[520px]:grid-cols-1`,
  decisionCopy:
    "grid min-w-0 gap-1 [&_p]:m-0 [&_p]:max-w-[76ch] [&_p]:text-[length:var(--vui-font-xs)] [&_p]:leading-[1.45] [&_p]:text-[var(--fg-secondary)] [&_small]:text-[length:var(--vui-font-xs)] [&_small]:font-semibold [&_small]:uppercase [&_small]:tracking-[0.06em] [&_small]:text-[var(--fg-tertiary)] [&_strong]:min-w-0 [&_strong]:text-[length:var(--vui-font-md)] [&_strong]:leading-[1.35] [&_strong]:text-[var(--fg-primary)]",
  delta:
    "grid min-w-[82px] justify-items-end gap-0.5 @max-[520px]:min-w-0 @max-[520px]:justify-items-start [&_span]:text-[length:var(--vui-font-xs)] [&_span]:text-[var(--fg-tertiary)] [&_strong]:text-xl [&_strong]:font-semibold [&_strong]:text-[var(--state-success)]",
  detail:
    `min-w-0 ${borderedSurface} [&_summary]:flex [&_summary]:min-h-9 [&_summary]:cursor-pointer [&_summary]:list-none [&_summary]:items-center [&_summary]:justify-between [&_summary]:gap-2 [&_summary]:px-3 [&_summary]:text-[length:var(--vui-font-xs)] [&_summary]:font-semibold [&_summary]:text-[var(--fg-primary)] [&_summary::-webkit-details-marker]:hidden`,
  detailMeta:
    "font-normal text-[var(--fg-tertiary)]",
  error:
    "m-0 rounded-lg border border-[color-mix(in_srgb,var(--state-error)_36%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-error)_7%,var(--vui-surface-row))] px-3 py-2 text-[length:var(--vui-font-xs)] leading-[1.45] text-[var(--state-error)]",
  evidenceItem:
    "grid min-w-0 grid-cols-[18px_minmax(0,1fr)] items-start gap-1.5 rounded-md bg-[var(--vui-control-muted)] px-2 py-1.5 text-[length:var(--vui-font-xs)] leading-[1.45] text-[var(--fg-secondary)] data-[tone=positive]:[&>span:first-child]:text-[var(--state-success)] data-[tone=warning]:[&>span:first-child]:text-[var(--state-warning)]",
  evidenceList:
    "grid min-w-0 content-start gap-1.5",
  evidenceSurface:
    `grid min-w-0 content-start gap-2 ${borderedSurface} p-2.5`,
  fileList:
    "grid min-w-0 gap-0 border-t border-[var(--vui-border-subtle)] px-3 py-1",
  fileRow:
    "grid min-w-0 grid-cols-[minmax(0,1fr)_max-content_max-content] items-center gap-2 border-b border-[color-mix(in_srgb,var(--vui-border-subtle)_72%,transparent)] py-1.5 last:border-b-0 max-[560px]:grid-cols-[minmax(0,1fr)_max-content] [&>code]:min-w-0 [&>code]:truncate [&>code]:text-[length:var(--vui-font-xs)] [&>code]:text-[var(--fg-primary)] [&>span]:text-[length:var(--vui-font-xs)] [&>span]:text-[var(--fg-tertiary)]",
  header:
    "flex min-w-0 items-start justify-between gap-3 max-[520px]:flex-col [&_h3]:m-0 [&_h3]:text-[length:var(--vui-font-md)] [&_h3]:font-semibold [&_h3]:text-[var(--fg-primary)] [&_p]:m-0 [&_p]:text-[length:var(--vui-font-xs)] [&_p]:text-[var(--fg-tertiary)]",
  impactGrid:
    "grid min-w-0 grid-cols-2 gap-1.5",
  impactItem:
    `grid min-w-0 gap-0.5 ${borderedSurface} px-2 py-1.5 [&_span]:text-[length:var(--vui-font-xs)] [&_span]:text-[var(--fg-tertiary)] [&_strong]:text-[length:var(--vui-font-sm)] [&_strong]:text-[var(--fg-primary)]`,
  metric:
    `grid min-w-0 gap-0.5 rounded-lg border border-[var(--vui-border-subtle)] ${vuiFlatPanelClass} px-2.5 py-2 [&_span]:text-[length:var(--vui-font-xs)] [&_span]:text-[var(--fg-tertiary)] [&_strong]:text-[length:var(--vui-font-md)] [&_strong]:font-semibold [&_strong]:text-[var(--fg-primary)] [&_small]:min-w-0 [&_small]:truncate [&_small]:text-[length:var(--vui-font-xs)] [&_small]:text-[var(--fg-secondary)]`,
  metrics:
    "grid min-w-0 grid-cols-2 gap-2 @min-[720px]:grid-cols-4",
  panel:
    "grid h-full min-h-0 min-w-0 content-start gap-2.5 overflow-auto p-3 [container-type:inline-size] [background:var(--vui-surface-base)]",
  runtimeEffect:
    "inline-flex min-w-0 items-center gap-1.5 text-[length:var(--vui-font-xs)] leading-[1.4] text-[var(--fg-secondary)] [&_svg]:shrink-0 [&_svg]:text-[var(--state-warning)]",
  rubricCriterionItem:
    "grid min-w-0 grid-cols-[max-content_minmax(0,1fr)] items-start gap-x-2 gap-y-1 rounded-md bg-[var(--vui-control-muted)] px-2 py-1.5 text-[length:var(--vui-font-xs)] leading-[1.45] text-[var(--fg-secondary)] [&>span:first-child]:whitespace-nowrap [&>span:first-child]:text-right [&>span:first-child]:tabular-nums [&>span:last-child]:min-w-0 [&>span:last-child]:[overflow-wrap:anywhere]",
  sectionHeading:
    "m-0 text-[length:var(--vui-font-sm)] font-semibold text-[var(--fg-primary)]",
} as const;

export default styles;
