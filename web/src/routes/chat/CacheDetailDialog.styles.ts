// Wave 8C: extracted from ChatCodingRoute.styles for CacheDetailDialog.tsx

import {
  vuiGlassPanelClass,
  vuiStateCoolInfoClass,
  vuiStateWarmSoftClass,
} from "../../design/vuiSurfaceRecipes";

const styles: Record<string, string> = {
  cacheDetailBody: `vui-routes-chatcodingroute cacheDetailBody min-w-0 ${vuiGlassPanelClass} p-2 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] max-h-[min(620px,calc(100dvh_-_238px))] overflow-auto [scrollbar-gutter:stable]`,
  cacheDetailBoundary: `vui-routes-chatcodingroute cacheDetailBoundary min-w-0 ${vuiGlassPanelClass} p-2`,
  cacheDetailBoundaryHit: `vui-routes-chatcodingroute cacheDetailBoundaryHit min-w-0 ${vuiGlassPanelClass} p-2 w-[var(--cache-boundary-hit-width)]`,
  cacheDetailBoundaryLabels: `vui-routes-chatcodingroute cacheDetailBoundaryLabels min-w-0 ${vuiGlassPanelClass} p-2`,
  cacheDetailBoundaryMiss: `vui-routes-chatcodingroute cacheDetailBoundaryMiss min-w-0 ${vuiGlassPanelClass} p-2 w-[var(--cache-boundary-miss-width)]`,
  cacheDetailBoundaryTrack: `vui-routes-chatcodingroute cacheDetailBoundaryTrack min-w-0 ${vuiGlassPanelClass} p-2 [&_span+span]:border-l [&_span+span]:border-[var(--vui-border-subtle)]`,
  cacheDetailBoundaryUnknown: `vui-routes-chatcodingroute cacheDetailBoundaryUnknown min-w-0 ${vuiGlassPanelClass} p-2 w-[var(--cache-boundary-unknown-width)]`,
  cacheDetailCalibrationNote: `vui-routes-chatcodingroute cacheDetailCalibrationNote min-w-0 ${vuiGlassPanelClass} p-2 !grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-[7px]`,
  cacheDetailCloseButton: `vui-routes-chatcodingroute cacheDetailCloseButton min-w-0 ${vuiGlassPanelClass} p-2 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] bg-[var(--vui-control-muted)] px-2 py-1 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55`,
  // Dialog shell: viewport max-h (see components/layout/dialogHeightPolicy.ts).,
  cacheDetailDialog: `vui-routes-chatcodingroute cacheDetailDialog min-w-0 ${vuiGlassPanelClass} p-2 w-[min(1120px,calc(100vw_-_44px))] max-h-[min(860px,calc(100dvh_-_52px))]`,
  cacheDetailDonutCenter: `vui-routes-chatcodingroute cacheDetailDonutCenter pointer-events-none absolute inset-0 m-auto grid size-[min(112px,40%)] min-w-0 place-self-center place-items-center ${vuiGlassPanelClass} p-2 text-center shadow-[var(--vui-shadow-hairline)]`,
  cacheDetailDonutLegend: `vui-routes-chatcodingroute cacheDetailDonutLegend min-w-0 ${vuiGlassPanelClass} p-2`,
  cacheDetailDonutPanel: `vui-routes-chatcodingroute cacheDetailDonutPanel min-w-0 ${vuiGlassPanelClass} p-2`,
  cacheDetailDonutShell:
    "vui-routes-chatcodingroute cacheDetailDonutShell min-w-0 relative grid size-[min(280px,72vw)] place-items-center overflow-hidden text-[var(--fg-primary)]",
  cacheDetailDonutSvg: `vui-routes-chatcodingroute cacheDetailDonutSvg min-w-0 size-full ${vuiGlassPanelClass} p-2`,
  cacheDetailEmpty: `vui-routes-chatcodingroute cacheDetailEmpty min-w-0 ${vuiGlassPanelClass} p-2 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]`,
  cacheDetailHeader:
    "vui-routes-chatcodingroute cacheDetailHeader min-w-0 flex flex-wrap items-center gap-1.5 px-0.5 pb-1",
  cacheDetailOverlay: `vui-routes-chatcodingroute cacheDetailOverlay min-w-0 ${vuiGlassPanelClass} p-2`,
  cacheDetailSegmentGroup: `vui-routes-chatcodingroute cacheDetailSegmentGroup min-w-0 ${vuiGlassPanelClass} p-2`,
  cacheDetailSegmentHeader:
    "vui-routes-chatcodingroute cacheDetailSegmentHeader min-w-0 flex flex-wrap items-center gap-1.5 px-0.5 pb-1",
  cacheDetailSegmentList: `vui-routes-chatcodingroute cacheDetailSegmentList min-w-0 ${vuiGlassPanelClass} p-2 grid min-h-0 content-start gap-1.5 overflow-auto`,
  cacheDetailSegmentMeta: `vui-routes-chatcodingroute cacheDetailSegmentMeta min-w-0 ${vuiGlassPanelClass} p-2 flex flex-wrap items-center gap-1.5`,
  cacheDetailSegmentRow: `vui-routes-chatcodingroute cacheDetailSegmentRow min-w-0 ${vuiGlassPanelClass} p-2 rounded-[var(--radius-control)] bg-[var(--vui-surface-row)]`,
  cacheDetailSegmentSource: `vui-routes-chatcodingroute cacheDetailSegmentSource min-w-0 ${vuiGlassPanelClass} p-2`,
  cacheDetailSegmentText: `vui-routes-chatcodingroute cacheDetailSegmentText min-w-0 ${vuiGlassPanelClass} p-2 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]`,
  cacheDetailSummaryGrid: `vui-routes-chatcodingroute cacheDetailSummaryGrid min-w-0 ${vuiGlassPanelClass} p-2 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]`,
  cacheDetailSwatch: `vui-routes-chatcodingroute cacheDetailSwatch min-w-0 ${vuiGlassPanelClass} p-2`,
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
