import type { SessionCacheCompositionSegment, SessionDetail } from "../../api/types";
import type { CacheDonutSegment } from "./CacheDetailDialog";

export const MIN_CACHE_DONUT_SEGMENT_PERCENT = 3;

export type SessionCacheCompositionDiagnostics = NonNullable<SessionDetail["lastCacheComposition"]> & {
  upperBoundInputTokens?: number;
  upperBoundCachedInputTokens?: number;
  upperBoundUncachedInputTokens?: number;
  upperBoundCacheHitRate?: number;
  predictedInputTokens?: number;
  predictedCachedInputTokens?: number;
  predictedUncachedInputTokens?: number;
  predictedCacheHitRate?: number;
  predictionStatus?: string;
  predictionReason?: string;
};

export function buildCacheDonutSegments(
  segments: SessionCacheCompositionSegment[],
  total: number,
  minPercent = MIN_CACHE_DONUT_SEGMENT_PERCENT,
): CacheDonutSegment[] {
  const totalTokens = Math.max(0, total);
  const positiveSegments = segments
    .map((segment) => ({
      ...segment,
      tokens: Math.max(0, segment.tokens ?? 0),
    }))
    .filter((segment) => segment.tokens > 0);
  if (!positiveSegments.length || totalTokens <= 0) {
    return [];
  }
  const rawSegments = positiveSegments.map((segment) => ({
    ...segment,
    actualPercent: (segment.tokens / totalTokens) * 100,
  }));
  const minVisualPercent = Math.max(0, minPercent);
  const minSegmentTotal = rawSegments.reduce(
    (sum, segment) => sum + (segment.actualPercent > 0 && segment.actualPercent < minVisualPercent ? minVisualPercent : 0),
    0,
  );
  const largeRawTotal = rawSegments.reduce(
    (sum, segment) => sum + (segment.actualPercent >= minVisualPercent ? segment.actualPercent : 0),
    0,
  );
  let cursor = 0;
  if (minSegmentTotal >= 100) {
    const sharedPercent = 100 / rawSegments.length;
    return rawSegments.map((segment, index) => {
      const startPercent = cursor;
      const visualPercent = index === rawSegments.length - 1 ? Math.max(0, 100 - cursor) : sharedPercent;
      cursor += visualPercent;
      return {
        ...segment,
        visualPercent,
        startPercent,
        visuallyAmplified: visualPercent > segment.actualPercent,
      };
    });
  }
  const largeScale = largeRawTotal > 0 ? (100 - minSegmentTotal) / largeRawTotal : 1;
  return rawSegments.map((segment, index) => {
    const startPercent = cursor;
    const isSmall = segment.actualPercent > 0 && segment.actualPercent < minVisualPercent;
    const rawVisualPercent = isSmall ? minVisualPercent : segment.actualPercent * largeScale;
    const visualPercent = index === rawSegments.length - 1 ? Math.max(0, 100 - cursor) : rawVisualPercent;
    cursor += visualPercent;
    return {
      ...segment,
      visualPercent,
      startPercent,
      visuallyAmplified: visualPercent > segment.actualPercent + 0.01,
    };
  });
}
