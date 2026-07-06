import { describe, expect, it } from "vitest";

import routeStyles from "../ChatCodingRoute.styles";
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
    expect(routeStyles.cacheDetailDonutShell).toContain("size-[");
    expect(routeStyles.cacheDetailDonutShell).toContain("place-items-center");
    expect(routeStyles.cacheDetailDonutSvg).toContain("size-full");
    expect(routeStyles.cacheDetailDonutCenter).toContain("absolute");
    expect(routeStyles.cacheDetailDonutCenter).toContain("inset-0");
    expect(routeStyles.cacheDetailDonutCenter).toContain("place-self-center");
    expect(routeStyles.cacheDetailDonutCenter).toContain("place-items-center");
    expect(routeStyles.cacheDetailDonutCenter).toContain("pointer-events-none");

    expect(routeStyles.cacheDonutTrack).toContain("fill-none");
    expect(routeStyles.cacheDonutTrack).toContain("stroke-[");
    expect(routeStyles.cacheDonutTrack).toContain("[stroke-linecap:round]");
    expect(routeStyles.cacheDonutTrack).toContain("[vector-effect:non-scaling-stroke]");
    expect(routeStyles.cacheDonutOuterTrack).toContain("[stroke-width:");
    expect(routeStyles.cacheDonutInnerTrack).toContain("[stroke-width:");

    expect(routeStyles.cacheDonutSegment).toContain("fill-none");
    expect(routeStyles.cacheDonutSegment).toContain("stroke-[");
    expect(routeStyles.cacheDonutSegment).toContain("[stroke-linecap:round]");
    expect(routeStyles.cacheDonutSegment).toContain("[vector-effect:non-scaling-stroke]");
    expect(routeStyles.cacheDonutOuterSegment).toContain("[stroke-width:");
    expect(routeStyles.cacheDonutInnerSegment).toContain("[stroke-width:");

    for (const key of donutSegmentToneKeys) {
      expect(routeStyles[key], key).toContain("stroke-[");
    }
  });
});
