import { describe, expect, it } from "vitest";

import { shouldRefitOnContainerResize } from "./workflowFitOnResize";

describe("shouldRefitOnContainerResize", () => {
  it("fits the first usable host box before the user pans", () => {
    expect(shouldRefitOnContainerResize({
      width: 720,
      height: 480,
      previousWidth: 0,
      previousHeight: 0,
      userMovedViewport: false,
    })).toBe(true);
  });

  it("re-fits when the inspector column changes the canvas width", () => {
    expect(shouldRefitOnContainerResize({
      width: 720,
      height: 480,
      previousWidth: 1080,
      previousHeight: 480,
      userMovedViewport: false,
    })).toBe(true);
  });

  it("does not steal a viewport the user already moved", () => {
    expect(shouldRefitOnContainerResize({
      width: 720,
      height: 480,
      previousWidth: 1080,
      previousHeight: 480,
      userMovedViewport: true,
    })).toBe(false);
  });

  it("ignores tiny jitter and collapsed hosts", () => {
    expect(shouldRefitOnContainerResize({
      width: 724,
      height: 480,
      previousWidth: 720,
      previousHeight: 480,
      userMovedViewport: false,
    })).toBe(false);
    expect(shouldRefitOnContainerResize({
      width: 12,
      height: 480,
      previousWidth: 0,
      previousHeight: 0,
      userMovedViewport: false,
    })).toBe(false);
  });
});
