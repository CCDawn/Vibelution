import { describe, expect, it } from "vitest";

import { canvasEdgeDisplayLabel, resolveEdgeLabelSpec } from "./workflowEdgeLabelGeometry";

describe("workflow edge label geometry", () => {
  it("keeps two CJK characters at the historical 34px box", () => {
    const spec = resolveEdgeLabelSpec("交接");
    expect(spec.displayText).toBe("交接");
    expect(spec.width).toBe(34);
    expect(spec.height).toBe(20);
  });

  it("maps Knowledge Package to a short Chinese canvas label instead of truncating ASCII as CJK", () => {
    expect(canvasEdgeDisplayLabel("Knowledge Package")).toBe("知识包");
    const spec = resolveEdgeLabelSpec("Knowledge Package");
    expect(spec.displayText).toBe("知识包");
    expect(spec.text).toBe("Knowledge Package");
    expect(spec.width).toBeLessThan(80);
    expect(spec.displayText).not.toContain("…");
  });

  it("does not ellipsize English that still fits the max width", () => {
    const spec = resolveEdgeLabelSpec("Promote");
    expect(spec.displayText).toBe("Promote");
    expect(spec.displayText).not.toContain("…");
  });
});
