import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const routeSource = readFileSync(resolve(import.meta.dirname, "ResearchFlowCanvasRoute.tsx"), "utf8");
const routerSource = readFileSync(resolve(import.meta.dirname, "../app/router.tsx"), "utf8");

describe("ResearchFlowCanvasRoute retired contract", () => {
  it("is a thin redirect and is not lazy-loaded as a page", () => {
    expect(routeSource).toContain("Navigate");
    expect(routeSource).toContain("researchView=workflow");
    expect(routeSource).toContain("panel=agents");
    expect(routerSource).toContain("ResearchFlowCanvasRedirect");
    expect(routerSource).not.toMatch(/import\("\.\.\/routes\/ResearchFlowCanvasRoute"\)/);
  });

  it("does not expose legacy execute writer UI", () => {
    expect(routeSource).not.toContain("/api/research/flow-canvas/execute");
  });
});
