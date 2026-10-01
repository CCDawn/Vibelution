import { describe, expect, it } from "vitest";

import {
  clampImagePreviewOffset,
  clampImageScale,
  IMAGE_PREVIEW_DEFAULT_OFFSET,
  IMAGE_PREVIEW_DOUBLE_CLICK_SCALE,
  IMAGE_PREVIEW_MAX_SCALE,
  IMAGE_PREVIEW_MIN_SCALE,
  IMAGE_PREVIEW_SCALE_STEPS,
  nextImagePreviewStepScale,
  panImagePreviewOffset,
  pinchImagePreviewScale,
  resetImagePreviewTransform,
  toggleImagePreviewScale,
  wheelImagePreviewScale,
  zoomImagePreviewAtAnchor,
} from "./conversationImageZoom";

describe("conversationImageZoom scale bounds", () => {
  it("clamps scale into the 25%-800% range", () => {
    expect(IMAGE_PREVIEW_MIN_SCALE).toBe(0.25);
    expect(IMAGE_PREVIEW_MAX_SCALE).toBe(8);
    expect(clampImageScale(-5)).toBe(0.25);
    expect(clampImageScale(0.25)).toBe(0.25);
    expect(clampImageScale(1.5)).toBe(1.5);
    expect(clampImageScale(8)).toBe(8);
    expect(clampImageScale(100)).toBe(8);
  });

  it("degrades non-finite scales to the default fit scale", () => {
    expect(clampImageScale(Number.NaN)).toBe(1);
    expect(clampImageScale(Number.POSITIVE_INFINITY)).toBe(8);
    expect(clampImageScale(Number.NEGATIVE_INFINITY)).toBe(0.25);
  });

  it("keeps the discrete steps inside the clamp range", () => {
    expect(IMAGE_PREVIEW_SCALE_STEPS[0]).toBe(IMAGE_PREVIEW_MIN_SCALE);
    expect(IMAGE_PREVIEW_SCALE_STEPS[IMAGE_PREVIEW_SCALE_STEPS.length - 1]).toBe(
      IMAGE_PREVIEW_MAX_SCALE,
    );
    for (let i = 1; i < IMAGE_PREVIEW_SCALE_STEPS.length; i += 1) {
      expect(IMAGE_PREVIEW_SCALE_STEPS[i]).toBeGreaterThan(
        IMAGE_PREVIEW_SCALE_STEPS[i - 1],
      );
    }
  });
});

describe("nextImagePreviewStepScale", () => {
  it("steps up through the discrete levels", () => {
    expect(nextImagePreviewStepScale(0.25, 1)).toBe(0.5);
    expect(nextImagePreviewStepScale(0.5, 1)).toBe(1);
    expect(nextImagePreviewStepScale(1, 1)).toBe(2);
    expect(nextImagePreviewStepScale(2, 1)).toBe(4);
    expect(nextImagePreviewStepScale(4, 1)).toBe(8);
  });

  it("steps down through the discrete levels", () => {
    expect(nextImagePreviewStepScale(8, -1)).toBe(4);
    expect(nextImagePreviewStepScale(4, -1)).toBe(2);
    expect(nextImagePreviewStepScale(2, -1)).toBe(1);
    expect(nextImagePreviewStepScale(1, -1)).toBe(0.5);
    expect(nextImagePreviewStepScale(0.5, -1)).toBe(0.25);
  });

  it("clamps at the range edges and rounds continuous values outward", () => {
    expect(nextImagePreviewStepScale(8, 1)).toBe(8);
    expect(nextImagePreviewStepScale(0.25, -1)).toBe(0.25);
    expect(nextImagePreviewStepScale(1.4, 1)).toBe(2);
    expect(nextImagePreviewStepScale(1.4, -1)).toBe(1);
    expect(nextImagePreviewStepScale(Number.NaN, 1)).toBe(2);
    expect(nextImagePreviewStepScale(Number.NaN, -1)).toBe(0.5);
  });
});

describe("wheelImagePreviewScale", () => {
  it("zooms in for negative deltaY and out for positive deltaY", () => {
    expect(wheelImagePreviewScale(1, -100)).toBeCloseTo(Math.exp(0.25), 12);
    expect(wheelImagePreviewScale(1, 100)).toBeCloseTo(Math.exp(-0.25), 12);
  });

  it("composes from the current scale", () => {
    expect(wheelImagePreviewScale(2, -100)).toBeCloseTo(2 * Math.exp(0.25), 12);
  });

  it("clamps at the bounds and ignores zero/non-finite deltas", () => {
    expect(wheelImagePreviewScale(8, -100)).toBe(8);
    expect(wheelImagePreviewScale(0.25, 100)).toBe(0.25);
    expect(wheelImagePreviewScale(1.5, 0)).toBe(1.5);
    expect(wheelImagePreviewScale(1.5, Number.NaN)).toBe(1.5);
  });
});

describe("pinchImagePreviewScale", () => {
  it("multiplies the start scale by the finger-distance ratio", () => {
    expect(pinchImagePreviewScale(1, 100, 150)).toBeCloseTo(1.5, 12);
    expect(pinchImagePreviewScale(1, 150, 100)).toBeCloseTo(2 / 3, 12);
    expect(pinchImagePreviewScale(4, 200, 50)).toBe(1);
  });

  it("clamps the ratio result into the scale range", () => {
    expect(pinchImagePreviewScale(8, 100, 400)).toBe(8);
    expect(pinchImagePreviewScale(0.25, 400, 10)).toBe(0.25);
  });

  it("falls back to the start scale for degenerate distances", () => {
    expect(pinchImagePreviewScale(4, 0, 100)).toBe(4);
    expect(pinchImagePreviewScale(4, 100, 0)).toBe(4);
    expect(pinchImagePreviewScale(4, Number.NaN, 100)).toBe(4);
  });
});

describe("clampImagePreviewOffset", () => {
  it("locks the offset to center when the scaled image fits the viewport", () => {
    const clamped = clampImagePreviewOffset(
      { x: 50, y: -40 },
      1,
      { width: 400, height: 300 },
      { width: 800, height: 600 },
    );
    expect(clamped).toEqual({ x: 0, y: 0 });
  });

  it("clamps the pan range to the overflow of the scaled image", () => {
    const clamped = clampImagePreviewOffset(
      { x: 1500, y: -2000 },
      2,
      { width: 1600, height: 1200 },
      { width: 800, height: 600 },
    );
    expect(clamped).toEqual({ x: 1200, y: -900 });
  });

  it("keeps offsets inside the allowed range untouched", () => {
    const clamped = clampImagePreviewOffset(
      { x: 300, y: -200 },
      2,
      { width: 1600, height: 1200 },
      { width: 800, height: 600 },
    );
    expect(clamped).toEqual({ x: 300, y: -200 });
  });

  it("handles degenerate sizes without producing NaN", () => {
    const clamped = clampImagePreviewOffset(
      { x: 10, y: 10 },
      2,
      { width: 0, height: 0 },
      { width: 800, height: 600 },
    );
    expect(clamped).toEqual({ x: 0, y: 0 });
    expect(Number.isFinite(clamped.x)).toBe(true);
  });
});

describe("zoomImagePreviewAtAnchor", () => {
  it("keeps the image point under the anchor fixed while zooming in", () => {
    const viewportSize = { width: 800, height: 600 };
    const anchor = { x: 200, y: 150 };
    const nextOffset = zoomImagePreviewAtAnchor({
      offset: { x: 0, y: 0 },
      scale: 1,
      nextScale: 2,
      anchor,
      viewportSize,
    });
    expect(nextOffset).toEqual({ x: 200, y: 150 });

    // Invariant: the image coordinate under the anchor is unchanged.
    const centerRelative = { x: anchor.x - 400, y: anchor.y - 300 };
    const before = {
      x: (centerRelative.x - 0) / 1,
      y: (centerRelative.y - 0) / 1,
    };
    const after = {
      x: (centerRelative.x - nextOffset.x) / 2,
      y: (centerRelative.y - nextOffset.y) / 2,
    };
    expect(after.x).toBeCloseTo(before.x, 12);
    expect(after.y).toBeCloseTo(before.y, 12);
  });

  it("accounts for an existing offset when anchoring", () => {
    const nextOffset = zoomImagePreviewAtAnchor({
      offset: { x: 50, y: -30 },
      scale: 1,
      nextScale: 2,
      anchor: { x: 600, y: 450 },
      viewportSize: { width: 800, height: 600 },
    });
    expect(nextOffset).toEqual({ x: -100, y: -210 });
  });

  it("zooming out returns to the previous framing for the same anchor", () => {
    const viewportSize = { width: 800, height: 600 };
    const anchor = { x: 650, y: 120 };
    const zoomedIn = zoomImagePreviewAtAnchor({
      offset: { x: 0, y: 0 },
      scale: 1,
      nextScale: 4,
      anchor,
      viewportSize,
    });
    const zoomedOut = zoomImagePreviewAtAnchor({
      offset: zoomedIn,
      scale: 4,
      nextScale: 1,
      anchor,
      viewportSize,
    });
    expect(zoomedOut.x).toBeCloseTo(0, 12);
    expect(zoomedOut.y).toBeCloseTo(0, 12);
  });

  it("returns the offset unchanged when the scale does not change", () => {
    const nextOffset = zoomImagePreviewAtAnchor({
      offset: { x: 33, y: -21 },
      scale: 2,
      nextScale: 2,
      anchor: { x: 10, y: 10 },
      viewportSize: { width: 800, height: 600 },
    });
    expect(nextOffset).toEqual({ x: 33, y: -21 });
  });
});

describe("panImagePreviewOffset", () => {
  it("adds the pointer delta to the drag-start offset", () => {
    const panned = panImagePreviewOffset(
      { x: 0, y: 0 },
      { x: 100, y: 100 },
      { x: 150, y: 140 },
    );
    expect(panned).toEqual({ x: 50, y: 40 });
    const continued = panImagePreviewOffset(
      { x: 50, y: 40 },
      { x: 150, y: 140 },
      { x: 120, y: 200 },
    );
    expect(continued).toEqual({ x: 20, y: 100 });
  });

  it("degrades non-finite input to a no-op pan", () => {
    const panned = panImagePreviewOffset(
      { x: 12, y: 34 },
      { x: Number.NaN, y: 0 },
      { x: 40, y: 0 },
    );
    expect(panned).toEqual({ x: 52, y: 34 });
  });
});

describe("toggleImagePreviewScale", () => {
  it("toggles between 1x and the double-click zoom level", () => {
    expect(IMAGE_PREVIEW_DOUBLE_CLICK_SCALE).toBe(2);
    expect(toggleImagePreviewScale(1)).toBe(2);
    expect(toggleImagePreviewScale(2)).toBe(1);
    expect(toggleImagePreviewScale(0.25)).toBe(2);
    expect(toggleImagePreviewScale(1.5)).toBe(2);
  });

  it("falls back to 1x from any zoomed-in level", () => {
    expect(toggleImagePreviewScale(3)).toBe(1);
    expect(toggleImagePreviewScale(8)).toBe(1);
    expect(toggleImagePreviewScale(Number.NaN)).toBe(2);
  });
});

describe("resetImagePreviewTransform", () => {
  it("returns a fresh fit transform with a centered offset", () => {
    const reset = resetImagePreviewTransform();
    expect(reset.scale).toBe(1);
    expect(reset.offset).toEqual({ x: 0, y: 0 });
  });

  it("hands out a mutable copy instead of the frozen default offset", () => {
    const reset = resetImagePreviewTransform();
    expect(reset.offset).not.toBe(IMAGE_PREVIEW_DEFAULT_OFFSET);
    expect(() => {
      reset.offset.x = 5;
    }).not.toThrow();
    expect(IMAGE_PREVIEW_DEFAULT_OFFSET.x).toBe(0);
  });
});
