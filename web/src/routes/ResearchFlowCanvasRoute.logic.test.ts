/**
 * Task 9: logic surface retired with independent page.
 * Keep a minimal contract so historical test path does not reintroduce dual SSOT.
 */
import { describe, expect, it } from "vitest";

import { validateResearchFlowCanvasContract } from "./ResearchFlowCanvasRoute";

describe("ResearchFlowCanvasRoute flow canvas rules (retired)", () => {
  it("no longer validates as an active execution canvas", () => {
    expect(validateResearchFlowCanvasContract({ nodes: [] }).valid).toBe(false);
  });
});
