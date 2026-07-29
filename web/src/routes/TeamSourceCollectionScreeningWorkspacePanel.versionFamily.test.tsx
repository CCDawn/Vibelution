import { describe, expect, it } from "vitest";

import panelSource from "./TeamSourceCollectionScreeningWorkspacePanel.tsx?raw";

describe("TeamSourceCollectionScreeningWorkspacePanel version family contract", () => {
  it("shows the version chain and prevents independent approval of superseded records", () => {
    expect(panelSource).toContain("sourceCollectionCandidateVersionFamily");
    expect(panelSource).toContain("versionFamily.chainLabel");
    expect(panelSource).toContain("versionFamily.evidenceLabel");
    expect(panelSource).toContain("sourceCollectionIndependentSourceCount");
    expect(panelSource).toContain("独立来源");
    expect(panelSource).toContain("versionFamily?.isSuperseded");
    expect(panelSource).toContain("versionFamily?.reviewDisabledReason");
  });
});
