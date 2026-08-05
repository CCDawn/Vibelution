import { describe, expect, it } from "vitest";

import routeStyles from "../ChatCodingRoute.styles";
import cacheDetailStyles from "./CacheDetailDialog.styles";
import cacheDetailDialogSource from "./CacheDetailDialog.tsx?raw";

const donutSegmentToneKeys = [
  "cacheDonutSegmentAgent",
  "cacheDonutSegmentAttachments",
  "cacheDonutSegmentCacheWrite",
  "cacheDonutSegmentCached",
  "cacheDonutSegmentGuidance",
  "cacheDonutSegmentHistory",
  "cacheDonutSegmentMissing",
  "cacheDonutSegmentOther",
  "cacheDonutSegmentProjectRules",
  "cacheDonutSegmentProviderUnmapped",
  "cacheDonutSegmentSkill",
  "cacheDonutSegmentSystem",
  "cacheDonutSegmentTask",
  "cacheDonutSegmentToolDescriptions",
  "cacheDonutSegmentToolSchema",
  "cacheDonutSegmentUncached",
  "cacheDonutSegmentUser",
] as const;

function resolveDonutTone(key: string): string {
  return (cacheDetailStyles as Record<string, string>)[key]
    ?? (routeStyles as Record<string, string>)[key]
    ?? "";
}

describe("CacheDetailDialog donut layout contract", () => {
  it("uses VDialog with title and description props", () => {
    expect(cacheDetailDialogSource).toContain("<VDialog");
    expect(cacheDetailDialogSource).toContain("title={cacheDetailDialogTitle}");
    expect(cacheDetailDialogSource).toContain("description={previousCacheHitLabel}");
  });

  it("keeps segment rows flat without glass nesting on atomic chrome", () => {
    expect(cacheDetailStyles.cacheDetailBody).toContain("md:grid-cols-[");
    expect(cacheDetailStyles.cacheDetailSegmentRow).toContain("grid-cols-[");
    expect(cacheDetailStyles.cacheDetailSegmentRow).not.toContain("vuiGlassPanelClass");
    expect(cacheDetailStyles.cacheDetailBoundaryTrack).toContain("flex");
    expect(cacheDetailStyles.cacheDetailBoundaryTrack).toContain("h-2");
    expect(cacheDetailStyles.cacheDetailBoundaryTrack).not.toMatch(/vuiGlass|p-2/);
    expect(cacheDetailStyles.cacheDetailBoundaryHit).toContain("w-[var(--cache-boundary-hit-width)]");
    expect(cacheDetailStyles.cacheDetailBoundaryHit).not.toMatch(/vuiGlass|p-2/);
    expect(cacheDetailStyles.cacheDetailSegmentMeta).toContain("flex");
    expect(cacheDetailStyles.cacheDetailSegmentMeta).toContain("gap-1");
    expect(cacheDetailStyles.cacheDetailSegmentMeta).not.toMatch(/vuiGlass|p-2\b/);
    expect(cacheDetailStyles.cacheDetailSwatch).toContain("size-2.5");
    expect(cacheDetailStyles.cacheDetailSwatch).not.toMatch(/vuiGlass|p-2\b/);
    expect(cacheDetailDialogSource).toContain("cacheDetailSegmentStats");
    expect(cacheDetailDialogSource).toContain('lang === "zh" ? "真实" : "obs"');
  });

  it("renders donut circles as stroke-only SVG rings", () => {
    const donutSvgStart = cacheDetailDialogSource.indexOf("<svg");
    const donutSvgEnd = cacheDetailDialogSource.indexOf("</svg>", donutSvgStart);
    const donutSvgSource = cacheDetailDialogSource.slice(donutSvgStart, donutSvgEnd);
    const circleTags = donutSvgSource.match(/<circle[\s\S]*?(?:\/>|>)/g) ?? [];

    expect(circleTags).toHaveLength(4);
    for (const circleTag of circleTags) {
      expect(circleTag).toContain('fill="none"');
    }
  });

  it("keeps donut tracks and segments visibly stroked", () => {
    expect(cacheDetailStyles.cacheDetailDonutShell).toContain("size-[");
    expect(cacheDetailStyles.cacheDetailDonutShell).toContain("place-items-center");
    expect(cacheDetailStyles.cacheDetailDonutSvg).toContain("size-full");
    expect(cacheDetailStyles.cacheDetailDonutCenter).toContain("absolute");
    expect(cacheDetailStyles.cacheDetailDonutCenter).toContain("inset-0");
    expect(cacheDetailStyles.cacheDetailDonutCenter).toContain("place-self-center");
    expect(cacheDetailStyles.cacheDetailDonutCenter).toContain("place-items-center");
    expect(cacheDetailStyles.cacheDetailDonutCenter).toContain("pointer-events-none");

    expect(cacheDetailStyles.cacheDonutTrack).toContain("fill-none");
    expect(cacheDetailStyles.cacheDonutTrack).toContain("stroke-[");
    expect(cacheDetailStyles.cacheDonutTrack).toContain("[stroke-linecap:round]");
    expect(cacheDetailStyles.cacheDonutTrack).toContain("[vector-effect:non-scaling-stroke]");
    expect(cacheDetailStyles.cacheDonutOuterTrack).toContain("[stroke-width:");
    expect(cacheDetailStyles.cacheDonutInnerTrack).toContain("[stroke-width:");

    expect(cacheDetailStyles.cacheDonutSegment).toContain("fill-none");
    expect(cacheDetailStyles.cacheDonutSegment).toContain("stroke-[");
    expect(cacheDetailStyles.cacheDonutSegment).toContain("[stroke-linecap:round]");
    expect(cacheDetailStyles.cacheDonutSegment).toContain("[vector-effect:non-scaling-stroke]");
    expect(cacheDetailStyles.cacheDonutOuterSegment).toContain("[stroke-width:");
    expect(cacheDetailStyles.cacheDonutInnerSegment).toContain("[stroke-width:");

    for (const key of donutSegmentToneKeys) {
      expect(resolveDonutTone(key), key).toContain("stroke-[");
    }
  });
});
