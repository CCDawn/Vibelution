import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const source = readFileSync(resolve(import.meta.dirname, "useResearchWorkflowRun.ts"), "utf8");

describe("useResearchWorkflowRun", () => {
  it("loads full run record not only canvas projection", () => {
    expect(source).toContain("fetchResearchWorkflowRun");
    expect(source).toContain("fetchResearchWorkflowCanvas");
    expect(source).toContain("fetchResearchWorkflowEvents");
    expect(source).toContain("bindingSnapshots");
    expect(source).toContain("handoffs");
    expect(source).toContain("langGraph");
  });

  it("polls events while run is active", () => {
    expect(source).toContain("afterSequence");
    expect(source).toContain("setInterval");
    expect(source).toContain("waiting_human");
  });
});
