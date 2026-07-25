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
  it("labels the dialog from visible title and description text", () => {
    expect(cacheDetailDialogSource).toContain("useId");
    expect(cacheDetailDialogSource).toContain("aria-labelledby={titleId}");
    expect(cacheDetailDialogSource).toContain("aria-describedby={descriptionId}");
    expect(cacheDetailDialogSource).not.toContain("aria-label={cacheDetailDialogTitle}");
    expect(cacheDetailDialogSource).toContain("<h3 id={titleId}>{cacheDetailDialogTitle}</h3>");
    expect(cacheDetailDialogSource).toContain("<p id={descriptionId}>{previousCacheHitLabel}</p>");
    expect(cacheDetailDialogSource).toContain("<X size={16} aria-hidden=\"true\" />");
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
