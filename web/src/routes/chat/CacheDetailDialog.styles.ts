// Wave 8C: extracted from ChatCodingRoute.styles for CacheDetailDialog.tsx
// Segment rows keep one surface chrome; atomic meta/boundary/swatch stay flat.

import {
  vuiGlassPanelClass,
  vuiStateCoolInfoClass,
  vuiStateWarmSoftClass,
} from "../../design/vuiSurfaceRecipes";

const styles: Record<string, string> = {
  // Two-column body: donut stays visible while segments scroll.
  cacheDetailBody:
    "vui-routes-chatcodingroute cacheDetailBody min-w-0 grid gap-3 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] max-h-[min(620px,calc(100dvh_-_238px))] overflow-auto [scrollbar-gutter:stable] md:grid-cols-[minmax(200px,260px)_minmax(0,1fr)] md:items-start",
  cacheDetailBoundary: "vui-routes-chatcodingroute cacheDetailBoundary min-w-0 grid gap-1",
  cacheDetailBoundaryHit:
    "vui-routes-chatcodingroute cacheDetailBoundaryHit block h-full min-w-0 bg-[var(--state-success)] w-[var(--cache-boundary-hit-width)]",
  cacheDetailBoundaryLabels:
    "vui-routes-chatcodingroute cacheDetailBoundaryLabels min-w-0 flex flex-wrap items-center gap-x-2.5 gap-y-0.5 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)] [&_[data-kind=hit]]:text-[var(--state-success)] [&_[data-kind=miss]]:text-[var(--state-warning)] [&_[data-kind=unknown]]:text-[var(--fg-tertiary)]",
  cacheDetailBoundaryMiss:
    "vui-routes-chatcodingroute cacheDetailBoundaryMiss block h-full min-w-0 bg-[var(--state-warning)] w-[var(--cache-boundary-miss-width)]",
  cacheDetailBoundaryTrack:
    "vui-routes-chatcodingroute cacheDetailBoundaryTrack flex h-2 w-full min-w-0 overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[color-mix(in_srgb,var(--vui-border-subtle)_55%,transparent)]",
  cacheDetailBoundaryUnknown:
    "vui-routes-chatcodingroute cacheDetailBoundaryUnknown block h-full min-w-0 bg-[color-mix(in_srgb,var(--fg-tertiary)_55%,transparent)] w-[var(--cache-boundary-unknown-width)]",
  cacheDetailCalibrationNote: `vui-routes-chatcodingroute cacheDetailCalibrationNote min-w-0 ${vuiGlassPanelClass} grid gap-1 p-2.5 [font-size:var(--vui-font-xs)] leading-snug text-[var(--fg-secondary)] [&_strong]:text-[var(--fg-primary)] [&_em]:text-[var(--fg-tertiary)] [&_em]:not-italic`,
  cacheDetailCloseButton: `vui-routes-chatcodingroute cacheDetailCloseButton min-w-0 ${vuiGlassPanelClass} p-2 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] bg-[var(--vui-control-muted)] px-2 py-1 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55`,
  // Dialog shell on VDialog content: viewport max-h (see components/layout/dialogHeightPolicy.ts).
  cacheDetailDialog: `vui-routes-chatcodingroute cacheDetailDialog min-w-0 w-[min(1120px,calc(100vw_-_44px))] max-h-[min(860px,calc(100dvh_-_52px))]`,
  cacheDetailDonutCenter:
    "vui-routes-chatcodingroute cacheDetailDonutCenter pointer-events-none absolute inset-0 m-auto grid size-[min(96px,38%)] min-w-0 place-self-center place-items-center rounded-full border border-[var(--vui-border-subtle)] bg-[color-mix(in_srgb,var(--vui-surface-panel)_92%,transparent)] p-2 text-center shadow-[var(--vui-shadow-hairline)] [&_strong]:[font-size:var(--vui-font-lg)] [&_strong]:font-semibold [&_strong]:text-[var(--fg-primary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:text-[var(--fg-tertiary)]",
  cacheDetailDonutLegend:
    "vui-routes-chatcodingroute cacheDetailDonutLegend min-w-0 grid gap-1 [font-size:var(--vui-font-xs)] leading-snug text-[var(--fg-tertiary)] [&_b]:mr-1 [&_b]:font-semibold [&_b]:text-[var(--fg-secondary)]",
  cacheDetailDonutPanel:
    "vui-routes-chatcodingroute cacheDetailDonutPanel min-w-0 grid justify-items-center gap-2 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-3 md:sticky md:top-0",
  cacheDetailDonutShell:
    "vui-routes-chatcodingroute cacheDetailDonutShell min-w-0 relative grid size-[min(240px,68vw)] place-items-center overflow-hidden text-[var(--fg-primary)]",
  cacheDetailDonutSvg:
    "vui-routes-chatcodingroute cacheDetailDonutSvg min-w-0 size-full",
  cacheDetailEmpty:
    "vui-routes-chatcodingroute cacheDetailEmpty min-w-0 px-1 py-2 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  cacheDetailHeader:
    "vui-routes-chatcodingroute cacheDetailHeader min-w-0 flex flex-wrap items-center gap-1.5 px-0.5 pb-1",
  cacheDetailOverlay: `vui-routes-chatcodingroute cacheDetailOverlay min-w-0 ${vuiGlassPanelClass} p-2`,
  cacheDetailSegmentGroup: "vui-routes-chatcodingroute cacheDetailSegmentGroup min-w-0 grid gap-1.5",
  cacheDetailSegmentHeader:
    "vui-routes-chatcodingroute cacheDetailSegmentHeader min-w-0 flex flex-wrap items-baseline justify-between gap-1.5 px-0.5 pb-0.5 [font-size:var(--vui-font-sm)] text-[var(--fg-primary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:font-normal [&_span]:text-[var(--fg-tertiary)]",
  cacheDetailSegmentList:
    "vui-routes-chatcodingroute cacheDetailSegmentList min-w-0 grid min-h-0 content-start gap-1.5",
  cacheDetailSegmentMeta:
    "vui-routes-chatcodingroute cacheDetailSegmentMeta min-w-0 flex flex-wrap items-center gap-1 [font-size:var(--vui-font-xs)] leading-tight [&_b]:rounded-full [&_b]:border [&_b]:border-[var(--vui-border-subtle)] [&_b]:bg-[color-mix(in_srgb,var(--vui-surface-panel)_80%,transparent)] [&_b]:px-1.5 [&_b]:py-0.5 [&_b]:font-medium [&_b]:text-[var(--fg-secondary)] [&_b[data-status=observed_hit]]:border-[color-mix(in_srgb,var(--state-success)_34%,var(--vui-border-subtle))] [&_b[data-status=observed_hit]]:text-[var(--state-success)] [&_b[data-status=observed_miss]]:border-[color-mix(in_srgb,var(--state-warning)_34%,var(--vui-border-subtle))] [&_b[data-status=observed_miss]]:text-[var(--state-warning)] [&_b[data-status=observed_partial]]:text-[var(--state-warning)] [&_b[data-status=not_observed]]:text-[var(--fg-tertiary)]",
  cacheDetailSegmentRow:
    "vui-routes-chatcodingroute cacheDetailSegmentRow min-w-0 grid grid-cols-[0.55rem_minmax(0,1fr)_auto] items-start gap-x-2 gap-y-1 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] px-2.5 py-2",
  cacheDetailSegmentSource:
    "vui-routes-chatcodingroute cacheDetailSegmentSource min-w-0 [font-size:var(--vui-font-xs)] leading-snug text-[var(--fg-tertiary)]",
  cacheDetailSegmentText:
    "vui-routes-chatcodingroute cacheDetailSegmentText min-w-0 grid gap-1 [font-size:var(--vui-font-sm)] leading-snug text-[var(--fg-secondary)] [&_strong]:text-[var(--fg-primary)] [&_strong]:font-semibold [&_small]:[font-size:var(--vui-font-xs)] [&_small]:leading-snug [&_small]:text-[var(--fg-tertiary)]",
  cacheDetailSegmentStats:
    "vui-routes-chatcodingroute cacheDetailSegmentStats min-w-0 grid justify-items-end gap-0.5 text-right [font-size:var(--vui-font-xs)] not-italic leading-tight text-[var(--fg-secondary)] [&_small]:block [&_small]:text-[var(--fg-tertiary)]",
  cacheDetailSummaryGrid: `vui-routes-chatcodingroute cacheDetailSummaryGrid min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))] p-0.5 [&_div]:min-w-0 [&_div]:rounded-[var(--radius-control)] [&_div]:border [&_div]:border-[var(--vui-border-subtle)] [&_div]:bg-[var(--vui-surface-row)] [&_div]:p-2.5 [&_div]:grid [&_div]:gap-0.5 [&_span]:[font-size:var(--vui-font-xs)] [&_span]:text-[var(--fg-tertiary)] [&_strong]:[font-size:var(--vui-font-lg)] [&_strong]:font-semibold [&_strong]:text-[var(--fg-primary)] [&_small]:[font-size:var(--vui-font-xs)] [&_small]:text-[var(--fg-secondary)]`,
  cacheDetailSummaryPrimary:
    "vui-routes-chatcodingroute cacheDetailSummaryPrimary !border-[color-mix(in_srgb,var(--accent-cool)_36%,var(--vui-border-subtle))] !bg-[color-mix(in_srgb,var(--accent-cool)_8%,var(--vui-surface-panel))] [&_strong]:text-[var(--accent-cool)]",
  cacheDetailSwatch:
    "vui-routes-chatcodingroute cacheDetailSwatch mt-1 block size-2.5 shrink-0 rounded-sm border border-[color-mix(in_srgb,currentColor_28%,var(--vui-border-subtle))] bg-current opacity-90",
  cacheDonutCenter:
    "vui-routes-chatcodingroute cacheDonutCenter min-w-0",
  cacheDonutInnerSegment:
    "vui-routes-chatcodingroute cacheDonutInnerSegment min-w-0 [stroke-width:7px]",
  cacheDonutInnerTrack:
    "vui-routes-chatcodingroute cacheDonutInnerTrack min-w-0 [stroke-width:7px]",
  cacheDonutOuterSegment:
    "vui-routes-chatcodingroute cacheDonutOuterSegment min-w-0 [stroke-width:8px]",
  cacheDonutOuterTrack:
    "vui-routes-chatcodingroute cacheDonutOuterTrack min-w-0 [stroke-width:8px]",
  cacheDonutSegment:
    "vui-routes-chatcodingroute cacheDonutSegment min-w-0 fill-none stroke-[currentColor] [stroke-linecap:round] [stroke-linejoin:round] [vector-effect:non-scaling-stroke] opacity-90",
  cacheDonutSegmentAgent:
    `vui-routes-chatcodingroute cacheDonutSegmentAgent min-w-0 ${vuiStateCoolInfoClass} stroke-[currentColor]`,
  cacheDonutSegmentAttachments:
    "vui-routes-chatcodingroute cacheDonutSegmentAttachments min-w-0 text-[var(--accent-warm)] stroke-[currentColor]",
  cacheDonutSegmentCacheWrite:
    "vui-routes-chatcodingroute cacheDonutSegmentCacheWrite min-w-0 text-[var(--accent-warm)] stroke-[currentColor]",
  cacheDonutSegmentCached:
    "vui-routes-chatcodingroute cacheDonutSegmentCached min-w-0 text-[var(--state-success)] stroke-[currentColor]",
  cacheDonutSegmentGuidance:
    "vui-routes-chatcodingroute cacheDonutSegmentGuidance min-w-0 text-[var(--accent-warm)] stroke-[currentColor]",
  cacheDonutSegmentHistory:
    "vui-routes-chatcodingroute cacheDonutSegmentHistory min-w-0 text-[var(--fg-secondary)] stroke-[currentColor]",
  cacheDonutSegmentMissing:
    "vui-routes-chatcodingroute cacheDonutSegmentMissing min-w-0 text-[var(--fg-tertiary)] stroke-[currentColor]",
  cacheDonutSegmentOther:
    "vui-routes-chatcodingroute cacheDonutSegmentOther min-w-0 text-[var(--fg-secondary)] stroke-[currentColor]",
  cacheDonutSegmentProjectRules:
    "vui-routes-chatcodingroute cacheDonutSegmentProjectRules min-w-0 text-[var(--accent-warm)] stroke-[currentColor]",
  cacheDonutSegmentProviderUnmapped:
    "vui-routes-chatcodingroute cacheDonutSegmentProviderUnmapped min-w-0 text-[var(--fg-tertiary)] stroke-[currentColor]",
  cacheDonutSegmentSkill:
    "vui-routes-chatcodingroute cacheDonutSegmentSkill min-w-0 text-[var(--accent-cool)] stroke-[currentColor]",
  cacheDonutSegmentSystem:
    "vui-routes-chatcodingroute cacheDonutSegmentSystem min-w-0 text-[var(--accent-cool)] stroke-[currentColor]",
  cacheDonutSegmentTask:
    "vui-routes-chatcodingroute cacheDonutSegmentTask min-w-0 text-[var(--state-warning)] stroke-[currentColor]",
  cacheDonutSegmentToolDescriptions:
    `vui-routes-chatcodingroute cacheDonutSegmentToolDescriptions min-w-0 ${vuiStateWarmSoftClass} stroke-[var(--accent-warm)]`,
  cacheDonutSegmentToolSchema:
    `vui-routes-chatcodingroute cacheDonutSegmentToolSchema min-w-0 font-mono [font-size:var(--vui-font-xs)] ${vuiStateWarmSoftClass} stroke-[var(--accent-warm)]`,
  cacheDonutSegmentUncached:
    "vui-routes-chatcodingroute cacheDonutSegmentUncached min-w-0 text-[var(--state-warning)] stroke-[currentColor]",
  cacheDonutSegmentUser:
    "vui-routes-chatcodingroute cacheDonutSegmentUser min-w-0 text-[var(--accent-cool)] stroke-[currentColor]",
  cacheDonutSvg:
    "vui-routes-chatcodingroute cacheDonutSvg min-w-0",
  cacheDonutTrack:
    "vui-routes-chatcodingroute cacheDonutTrack min-w-0 fill-none stroke-[color-mix(in_srgb,var(--vui-border-subtle)_82%,transparent)] [stroke-linecap:round] [vector-effect:non-scaling-stroke]",
  contextCompositionSegmentProjectRules:
    `vui-routes-chatcodingroute contextCompositionSegmentProjectRules min-w-0 ${vuiStateWarmSoftClass}`,
  contextCompositionSegmentProviderUnmapped:
    `vui-routes-chatcodingroute contextCompositionSegmentProviderUnmapped min-w-0 ${vuiStateWarmSoftClass}`,
  contextCompositionSegmentSystem:
    `vui-routes-chatcodingroute contextCompositionSegmentSystem min-w-0 ${vuiStateWarmSoftClass}`,
  contextCompositionSegmentToolDescriptions:
    `vui-routes-chatcodingroute contextCompositionSegmentToolDescriptions min-w-0 ${vuiStateWarmSoftClass}`,
  contextCompositionSegmentToolSchema:
    `vui-routes-chatcodingroute contextCompositionSegmentToolSchema min-w-0 font-mono [font-size:var(--vui-font-xs)] ${vuiStateWarmSoftClass}`,
  cacheDonutShell:
    "vui-routes-chatcodingroute cacheDonutShell min-w-0 grid h-full min-h-0 content-start overflow-hidden text-[var(--fg-primary)]",
  cacheDonutStats:
    "vui-routes-chatcodingroute cacheDonutStats min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  contextCompositionSegmentCacheWrite:
    `vui-routes-chatcodingroute contextCompositionSegmentCacheWrite min-w-0 ${vuiStateWarmSoftClass}`,
  contextCompositionSegmentCached:
    `vui-routes-chatcodingroute contextCompositionSegmentCached min-w-0 ${vuiStateWarmSoftClass}`,
  contextCompositionSegmentExact:
    `vui-routes-chatcodingroute contextCompositionSegmentExact min-w-0 ${vuiStateWarmSoftClass}`,
  contextCompositionSegmentMissing:
    `vui-routes-chatcodingroute contextCompositionSegmentMissing min-w-0 ${vuiStateWarmSoftClass}`,
  contextCompositionSegmentUncached:
    `vui-routes-chatcodingroute contextCompositionSegmentUncached min-w-0 ${vuiStateWarmSoftClass}`,
  contextCompositionSegmentUnused:
    `vui-routes-chatcodingroute contextCompositionSegmentUnused min-w-0 ${vuiStateWarmSoftClass}`,
};

export default styles;
