import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const source = readFileSync(new URL("./ProgressiveRegionSkeleton.tsx", import.meta.url), "utf8");

describe("ProgressiveRegionSkeleton contract", () => {
  it("documents progressive-fill product contract and exposes stable variants", () => {
    expect(source).toContain("Do not swap an entire workbench main region");
    expect(source).toContain('data-testid="progressive-region-skeleton"');
    expect(source).toContain('variant === "list"');
    expect(source).toContain('variant === "session"');
    expect(source).toContain("min-h-[44px]");
    expect(source).toContain("min-h-[104px]");
    expect(source).toContain('variant === "detail"');
    expect(source).toContain('variant === "panel"');
    expect(source).toContain('variant === "canvas"');
    expect(source).toContain('variant === "conversation"');
    expect(source).toContain("aria-busy");
  });
});
