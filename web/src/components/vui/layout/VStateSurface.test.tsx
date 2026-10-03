import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { VStateSurface, type VStateSurfaceProps } from "./VStateSurface";

function renderState(props: Partial<VStateSurfaceProps> = {}) {
  return renderToStaticMarkup(<VStateSurface title="状态" {...props} />);
}

function skeletonCount(markup: string) {
  return (markup.match(/animate-pulse/g) ?? []).length;
}

describe("VStateSurface loading contract", () => {
  it.each(["empty", "error", "unavailable", "info"] as const)(
    "does not imply loading when a %s surface fills the region",
    (tone) => {
      const markup = renderState({ tone, fill: true });
      expect(skeletonCount(markup)).toBe(0);
      expect(markup).not.toContain('aria-busy="true"');
      expect(markup).toContain('data-fill="true"');
    },
  );

  it("does not animate explicit skeleton lines after loading has ended", () => {
    expect(skeletonCount(renderState({ tone: "empty", fill: true, skeletonLines: 3 }))).toBe(0);
  });

  it("preserves the inline and full-region loading geometry", () => {
    expect(skeletonCount(renderState({ tone: "loading" }))).toBe(2);
    expect(skeletonCount(renderState({ tone: "loading", fill: true }))).toBe(3);
    expect(renderState({ tone: "loading" })).toContain('aria-busy="true"');
  });

  it("uses the explicit busy state for both skeletons and accessibility", () => {
    expect(skeletonCount(renderState({ tone: "info", busy: true, skeletonLines: 1 }))).toBe(1);
    const settled = renderState({ tone: "loading", fill: true, busy: false });
    expect(skeletonCount(settled)).toBe(0);
    expect(settled).not.toContain('aria-busy="true"');
  });

  it("honors disabled skeletons and bounds the requested line count", () => {
    expect(skeletonCount(renderState({ tone: "loading", skeletonLines: false }))).toBe(0);
    expect(skeletonCount(renderState({ tone: "loading", skeletonLines: 20 }))).toBe(3);
  });
});
